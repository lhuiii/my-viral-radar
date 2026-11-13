-- ============================================================
-- 管理竞对 · 让团队在网页上加 / 停竞对(Instagram、Facebook)
--
-- 用法:Supabase → SQL Editor → New query → 整段粘贴 → Run。
-- ⚠️ 先把最底下「设置团队口令」那一行的口令换成你自己的(至少 8 个字符)。
--    没改会报错,改完整段重跑即可。可以安全重复跑,不会删任何数据。
--
-- 安全设计(为什么不直接让网页写 competitors 表):
--   网页里的公开钥匙谁都拿得到。每个竞对每周都会花 Apify 的钱,
--   所以加 / 停竞对必须带「团队口令」,而且:
--   · 网页只能调用下面几个函数,不能直接读写 competitors 表和设置表
--   · GitHub 令牌只存在数据库里,网页读不到,也读不回来
--   · 口令只存哈希,连口令本身都不会存进数据库
--   · 连续输错 8 次,锁定 10 分钟(按访问者 IP 分开记,别人乱试不会把你们锁在外面)
--   · 活跃竞对总数有上限(默认 30,见 app_settings.max_active_competitors)
--   · 平台只能是 IG 或 FB,账号名只能是字母、数字、点、下划线、横线
-- ============================================================

-- ---------- 设置表(网页读不到,revoke 过) ----------
create table if not exists app_settings (
  key   text primary key,
  value text not null
);
alter table app_settings enable row level security;
revoke all on app_settings from anon, authenticated;

-- 输错口令的记录,按访问者(IP)分开记:别人乱试只会锁他自己,不会把你的团队也锁在外面
create table if not exists admin_attempts (
  client       text primary key,
  fails        int not null default 0,
  locked_until timestamptz,
  updated_at   timestamptz not null default now()
);
alter table admin_attempts enable row level security;
revoke all on admin_attempts from anon, authenticated;

-- 活跃竞对上限。想改:update app_settings set value = '40' where key = 'max_active_competitors';
insert into app_settings (key, value) values ('max_active_competitors', '30')
on conflict (key) do nothing;

-- ---------- 自动触发抓取:加新账号后,让 GitHub 马上抓这个新账号 ----------
-- 网页(公开)不能存 GitHub 令牌,所以由数据库代发:令牌存在 app_settings,
-- 网页读不到。令牌和仓库名在网页「管理竞对 → 自动抓取设置」里填,不用回到这里。
-- pg_net 是 Supabase 自带的扩展(异步发 HTTP 请求),这里尝试启用。
do $$
begin
  create extension if not exists pg_net with schema extensions;
exception when others then
  raise notice 'pg_net 没能自动启用,请到 Supabase → Database → Extensions 里手动打开 pg_net';
end $$;

-- 内部:触发一次「只抓新账号」的 Sync Content。返回 sent / no_token / error
create or replace function _trigger_sync() returns text
language plpgsql security definer set search_path = public as $$
declare
  tok  text;
  repo text;
begin
  select value into tok  from app_settings where key = 'github_token';
  select value into repo from app_settings where key = 'github_repo';
  if tok is null or repo is null then
    return 'no_token';
  end if;
  begin
    perform net.http_post(
      url     := 'https://api.github.com/repos/' || repo || '/actions/workflows/sync.yml/dispatches',
      body    := jsonb_build_object('ref', 'main', 'inputs', jsonb_build_object('only_new', 'true')),
      headers := jsonb_build_object(
                   'Authorization', 'Bearer ' || tok,
                   'Accept', 'application/vnd.github+json',
                   'X-GitHub-Api-Version', '2022-11-28',
                   'User-Agent', 'viral-radar',
                   'Content-Type', 'application/json'));
    return 'sent';
  exception when others then
    return 'error';
  end;
end $$;

-- ---------- 内部:检查口令(网页不能直接调用) ----------
-- 内部:这次请求是谁发的(Supabase 网关带的 IP 头;读不到就当成同一个人)
create or replace function _client_key() returns text
language plpgsql stable set search_path = public as $$
declare
  h json;
  k text;
begin
  begin
    h := nullif(current_setting('request.headers', true), '')::json;
  exception when others then
    h := null;
  end;
  k := coalesce(nullif(h->>'cf-connecting-ip', ''),
                nullif(btrim(split_part(coalesce(h->>'x-forwarded-for', ''), ',', 1)), ''),
                'global');
  return left(k, 64);
end $$;

create or replace function _admin_check(p_pass text) returns text
language plpgsql security definer set search_path = public as $$
declare
  ck text := _client_key();
  st admin_attempts;
  h  text;
begin
  insert into admin_attempts (client) values (ck) on conflict do nothing;
  delete from admin_attempts where updated_at < now() - interval '1 day' and client <> ck;
  select * into st from admin_attempts where client = ck for update;
  if st.locked_until is not null and st.locked_until > now() then
    return 'locked';
  end if;
  select value into h from app_settings where key = 'admin_hash';
  if h is null then
    return 'no_passcode';
  end if;
  if p_pass is not null
     and encode(sha256(convert_to(p_pass, 'UTF8')), 'hex') = h then
    update admin_attempts set fails = 0, locked_until = null, updated_at = now() where client = ck;
    return 'ok';
  end if;
  if st.fails + 1 >= 8 then
    update admin_attempts set fails = 0, locked_until = now() + interval '10 minutes',
           updated_at = now() where client = ck;
  else
    update admin_attempts set fails = fails + 1, updated_at = now() where client = ck;
  end if;
  return 'bad_passcode';
end $$;

-- ---------- 网页用:验证口令 ----------
create or replace function verify_admin(p_pass text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare r text := _admin_check(p_pass);
begin
  return jsonb_build_object('ok', r = 'ok', 'error', case when r = 'ok' then null else r end);
end $$;

-- ---------- 网页用:列出所有竞对(只读,不需要口令) ----------
create or replace function list_competitors()
returns table (id bigint, username text, tracker text, active boolean, notes text)
language sql stable security definer set search_path = public as $$
  select id, username, tracker, active, notes
    from competitors
   order by active desc, tracker, lower(username);
$$;

-- ---------- 网页用:加竞对 ----------
-- p_platform: 'IG' 或 'FB'。p_input: 账号名,或账号 / 主页链接。
-- p_sync:加好后是否马上通知 GitHub 抓取。一次加好几个时,网页只在最后一个传 true,只触发一次。
drop function if exists add_competitor(text, text, text);
create or replace function add_competitor(p_pass text, p_platform text, p_input text,
                                          p_sync boolean default true)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  chk      text;
  plat     text := upper(btrim(coalesce(p_platform, '')));
  v        text := btrim(coalesce(p_input, ''));
  detected text;
  maxn     int;
  cnt      int;
  ex       competitors;
  reserved text[] := array['p','reel','reels','stories','tv','explore','accounts',
    'posts','photo','photos','videos','watch','groups','events','share',
    'permalink.php','story.php','profile.php','hashtag'];
begin
  chk := _admin_check(p_pass);
  if chk <> 'ok' then
    return jsonb_build_object('ok', false, 'error', chk);
  end if;
  if plat not in ('IG', 'FB') then
    return jsonb_build_object('ok', false, 'error', 'bad_platform');
  end if;
  if length(v) > 300 then
    return jsonb_build_object('ok', false, 'error', 'bad_handle');
  end if;

  if v ~* '(instagram\.com|facebook\.com|fb\.com)' then
    detected := case when v ~* 'instagram\.com' then 'IG' else 'FB' end;
    if detected <> plat then
      return jsonb_build_object('ok', false, 'error', 'platform_mismatch');
    end if;
    v := substring(v from '(?i)(?:instagram\.com|facebook\.com|fb\.com)/([^/?#]+)');
  end if;
  v := lower(ltrim(btrim(coalesce(v, '')), '@'));
  if v = '' or v = any(reserved) or v !~ '^[a-z0-9._-]{1,80}$' then
    return jsonb_build_object('ok', false, 'error', 'bad_handle');
  end if;

  select * into ex from competitors where lower(username) = v and tracker = plat limit 1;
  select coalesce((select value::int from app_settings where key = 'max_active_competitors'), 30)
    into maxn;
  select count(*) into cnt from competitors where active;

  if ex.id is not null then
    if ex.active then
      return jsonb_build_object('ok', true, 'status', 'exists', 'username', v, 'tracker', plat);
    end if;
    if cnt >= maxn then
      return jsonb_build_object('ok', false, 'error', 'limit_reached', 'max', maxn);
    end if;
    -- 恢复时清掉「抓取失败」标记,让它有机会再抓一次
    update competitors
       set active = true,
           notes  = case when notes like '抓取失败%' then null else notes end
     where id = ex.id;
    return jsonb_build_object('ok', true, 'status', 'reactivated', 'username', v, 'tracker', plat)
           || case when p_sync then jsonb_build_object('sync', _trigger_sync()) else '{}'::jsonb end;
  end if;

  if cnt >= maxn then
    return jsonb_build_object('ok', false, 'error', 'limit_reached', 'max', maxn);
  end if;
  insert into competitors (username, tracker, active, notes)
  values (v, plat, true,
          '网页添加 ' || to_char(now() at time zone 'Asia/Kuala_Lumpur', 'YYYY-MM-DD'));
  return jsonb_build_object('ok', true, 'status', 'added', 'username', v, 'tracker', plat)
         || case when p_sync then jsonb_build_object('sync', _trigger_sync()) else '{}'::jsonb end;
end $$;

-- ---------- 网页用:停 / 恢复某个竞对(保留历史数据) ----------
create or replace function set_competitor_active(p_pass text, p_id bigint, p_active boolean)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare
  chk  text;
  r    competitors;
  maxn int;
  cnt  int;
begin
  chk := _admin_check(p_pass);
  if chk <> 'ok' then
    return jsonb_build_object('ok', false, 'error', chk);
  end if;
  select * into r from competitors where id = p_id;
  if r.id is null then
    return jsonb_build_object('ok', false, 'error', 'not_found');
  end if;
  if p_active and not r.active then
    select coalesce((select value::int from app_settings where key = 'max_active_competitors'), 30)
      into maxn;
    select count(*) into cnt from competitors where active;
    if cnt >= maxn then
      return jsonb_build_object('ok', false, 'error', 'limit_reached', 'max', maxn);
    end if;
  end if;
  update competitors
     set active = p_active,
         notes  = case when p_active and notes like '抓取失败%' then null else notes end
   where id = p_id;
  -- 恢复一个从没抓过的账号(例如系统推荐的)时也触发;已有帖子的账号不会被重复抓
  if p_active and not r.active then
    return jsonb_build_object('ok', true, 'sync', _trigger_sync());
  end if;
  return jsonb_build_object('ok', true);
end $$;

-- ---------- 网页用:更换团队口令(要先输入现在的口令) ----------
-- 换了之后,其他人浏览器里存的旧口令会失效,下次操作时重新输入新口令即可。
create or replace function change_passcode(p_pass text, p_new text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare chk text;
begin
  chk := _admin_check(p_pass);
  if chk <> 'ok' then
    return jsonb_build_object('ok', false, 'error', chk);
  end if;
  if p_new is null or length(p_new) < 8 or length(p_new) > 100 then
    return jsonb_build_object('ok', false, 'error', 'weak_passcode');
  end if;
  insert into app_settings (key, value)
  values ('admin_hash', encode(sha256(convert_to(p_new, 'UTF8')), 'hex'))
  on conflict (key) do update set value = excluded.value;
  return jsonb_build_object('ok', true);
end $$;

-- ---------- 网页用:现在就抓新账号(一次加好几个之后,或补设好令牌之后用) ----------
create or replace function trigger_sync(p_pass text) returns jsonb
language plpgsql security definer set search_path = public as $$
declare chk text;
begin
  chk := _admin_check(p_pass);
  if chk <> 'ok' then
    return jsonb_build_object('ok', false, 'error', chk);
  end if;
  return jsonb_build_object('ok', true, 'sync', _trigger_sync());
end $$;

-- ---------- 网页用:自动抓取设置 ----------
-- 看有没有设置好(不返回令牌本身,只返回仓库名)
create or replace function github_status() returns jsonb
language sql stable security definer set search_path = public as $$
  select jsonb_build_object(
    'configured', exists (select 1 from app_settings where key = 'github_token')
                  and exists (select 1 from app_settings where key = 'github_repo'),
    'repo', (select value from app_settings where key = 'github_repo'));
$$;

-- 保存 / 清除 GitHub 仓库名和令牌。p_token 传空字符串 = 清除。
create or replace function set_github_settings(p_pass text, p_repo text, p_token text)
returns jsonb
language plpgsql security definer set search_path = public as $$
declare chk text;
begin
  chk := _admin_check(p_pass);
  if chk <> 'ok' then
    return jsonb_build_object('ok', false, 'error', chk);
  end if;
  if coalesce(p_token, '') = '' then
    delete from app_settings where key in ('github_token', 'github_repo');
    return jsonb_build_object('ok', true, 'status', 'cleared');
  end if;
  if p_repo is null or p_repo !~ '^[A-Za-z0-9._-]{1,100}/[A-Za-z0-9._-]{1,100}$' then
    return jsonb_build_object('ok', false, 'error', 'bad_repo');
  end if;
  if p_token !~ '^(github_pat_|ghp_)[A-Za-z0-9_]{20,255}$' then
    return jsonb_build_object('ok', false, 'error', 'bad_token');
  end if;
  insert into app_settings (key, value) values ('github_repo', p_repo)
    on conflict (key) do update set value = excluded.value;
  insert into app_settings (key, value) values ('github_token', p_token)
    on conflict (key) do update set value = excluded.value;
  return jsonb_build_object('ok', true, 'status', 'saved');
end $$;

-- ---------- 权限:网页(anon)只能调用这 4 个函数 ----------
revoke all on function _admin_check(text) from public, anon, authenticated;
revoke all on function _trigger_sync() from public, anon, authenticated;
revoke all on function github_status() from public;
revoke all on function set_github_settings(text, text, text) from public;
grant execute on function github_status() to anon;
grant execute on function set_github_settings(text, text, text) to anon;
revoke all on function verify_admin(text) from public;
revoke all on function list_competitors() from public;
revoke all on function _client_key() from public, anon, authenticated;
revoke all on function trigger_sync(text) from public;
grant execute on function trigger_sync(text) to anon;
revoke all on function change_passcode(text, text) from public;
grant execute on function change_passcode(text, text) to anon;
revoke all on function add_competitor(text, text, text, boolean) from public;
revoke all on function set_competitor_active(text, bigint, boolean) from public;
grant execute on function verify_admin(text)                        to anon;
grant execute on function list_competitors()                        to anon;
grant execute on function add_competitor(text, text, text, boolean) to anon;
grant execute on function set_competitor_active(text, bigint, boolean) to anon;

-- ============================================================
-- ↓↓↓ 设置团队口令:把下面单引号里的「换成你的口令」改成你自己的 ↓↓↓
--   · 至少 8 个字符,不要用生日、电话号码
--   · 口令只存哈希。以后想换口令,直接在网页「管理竞对 → 更换团队口令」里换就行
--     (只有忘记口令时,才需要改这一行、把整段重跑一次)
--   · 没改会报错,而且整段不会生效(安全起见)
-- ============================================================
do $$
declare
  p text := '换成你的口令';
begin
  if p = '换成你的口令' or length(p) < 8 then
    raise exception '请先把 p 改成你自己的口令(至少 8 个字符),再整段重跑';
  end if;
  insert into app_settings (key, value)
  values ('admin_hash', encode(sha256(convert_to(p, 'UTF8')), 'hex'))
  on conflict (key) do update set value = excluded.value;
  delete from admin_attempts;
end $$;
