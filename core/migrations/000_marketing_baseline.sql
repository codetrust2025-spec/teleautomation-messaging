CREATE TABLE IF NOT EXISTS ai_smart_reply_store (
    id TEXT PRIMARY KEY,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);
