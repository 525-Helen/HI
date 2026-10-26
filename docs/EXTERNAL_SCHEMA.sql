-- ============================================================
-- AI个性化饮食管理 Agent —— 外部主机部署用建表脚本（PostgreSQL / Supabase）
-- 在 Supabase 控制台 → SQL Editor 中一次性执行。
-- 表结构必须与「原 Coze/Supabase 实例」保持一致，否则 Agent 读写会报错。
-- ============================================================

-- 1) 用户身体档案（user_profiles）
--    PROFILE_KEY 用于未声明用户时的全局兜底（user_key = 'default'）。
CREATE TABLE IF NOT EXISTS public.user_profiles (
    id                  BIGSERIAL PRIMARY KEY,
    user_key            TEXT NOT NULL DEFAULT 'default',
    gender              TEXT NOT NULL DEFAULT 'male',
    age                 INT,
    height_cm           INT,
    weight_kg           NUMERIC,
    activity_level      TEXT NOT NULL DEFAULT 'sedentary',
    goal                TEXT NOT NULL DEFAULT 'normal',
    daily_calorie_target NUMERIC,
    diet_plan           TEXT,
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_user_profiles_user_key UNIQUE (user_key)
);

-- 2) 用户偏好（user_preference）：过敏原 + 忌口 + 目标
CREATE TABLE IF NOT EXISTS public.user_preference (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL DEFAULT 'default',
    allergens           TEXT NOT NULL DEFAULT '[]',   -- JSON 数组字符串
    dislikes            TEXT NOT NULL DEFAULT '[]',   -- JSON 数组字符串
    goal_type           TEXT NOT NULL DEFAULT 'normal',
    updated_at          TIMESTAMPTZ DEFAULT now(),
    CONSTRAINT uq_user_preference_user_id UNIQUE (user_id)
);

-- 3) 饮食记录（meal_records）
CREATE TABLE IF NOT EXISTS public.meal_records (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT,                          -- 多用户隔离；空 = 全局记录
    meal_type           TEXT NOT NULL DEFAULT 'snack', -- breakfast/lunch/dinner/snack
    meal_date           TEXT NOT NULL,                 -- YYYY-MM-DD
    calories            INT NOT NULL DEFAULT 0,
    food_items          JSONB DEFAULT '[]'::jsonb,     -- [{name, calories}]
    notes               TEXT,
    request_id          TEXT,                          -- 幂等键（防重复提交）
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- 索引：按用户 + 日期快速查询；request_id 幂等去重（并发场景由唯一索引兜底）
CREATE INDEX IF NOT EXISTS idx_meal_records_user_date
    ON public.meal_records (user_id, meal_date);
CREATE UNIQUE INDEX IF NOT EXISTS uq_meal_records_request_id
    ON public.meal_records (request_id)
    WHERE request_id IS NOT NULL;

-- 4) RLS（可选强化）：以下开启按 user_id 的行级安全。
--    若你的外部前端通过 anon key + 客户端过滤即可满足隔离，可暂不开启 RLS，
--    保持与当前 Coze 实例一致的行为（服务端统一按 user_id 过滤）。
-- ALTER TABLE public.user_profiles  ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.user_preference ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE public.meal_records    ENABLE ROW LEVEL SECURITY;

CREATE POLICY IF NOT EXISTS meal_records_all ON public.meal_records FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS user_profiles_all ON public.user_profiles FOR ALL USING (true);
CREATE POLICY IF NOT EXISTS user_preference_all ON public.user_preference FOR ALL USING (true);