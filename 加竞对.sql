-- ============================================================
-- 加竞对专用。只跑这一段,永远不要重跑 schema.sql 的整段。
-- 账号名:纯账号名,不要 @,不要链接。重复跑不会报错。
-- ============================================================
insert into competitors (username, tracker, active) values
  ('新竞对1', 'IG', true),
  ('新竞对2', 'IG', true),
  ('新竞对3', 'IG', true)
on conflict do nothing;

-- ------------------------------------------------------------
-- 加 Facebook 竞对(tracker 填 'FB')。
-- username 填 Facebook 公开主页的名字,也就是网址 facebook.com/ 后面那一段,
-- 例如 facebook.com/deluxmalaysia 就填 deluxmalaysia。
-- 也可以直接贴主页链接。只能是公开「主页」,不能是个人账号、群组或单条帖子链接。
-- 同一家公司 IG 和 FB 名字一样也没关系,各加一行就行。
-- ------------------------------------------------------------
-- insert into competitors (username, tracker, active) values
--   ('FB主页名1', 'FB', true),
--   ('FB主页名2', 'FB', true)
-- on conflict do nothing;

-- 想停掉某个竞对(保留数据,只是不再抓):
-- update competitors set active = false where lower(username) = lower('要停的账号名');

-- 看现在在追踪哪些:
-- select username, tracker, active, notes from competitors order by active desc, username;
