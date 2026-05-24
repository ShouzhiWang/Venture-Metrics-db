CREATE TABLE IF NOT EXISTS demo_feedback (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  answer_id TEXT,
  result_id TEXT,
  feedback_type TEXT NOT NULL,
  comment TEXT,
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_demo_feedback_answer_id ON demo_feedback(answer_id);
CREATE INDEX IF NOT EXISTS idx_demo_feedback_result_id ON demo_feedback(result_id);
CREATE INDEX IF NOT EXISTS idx_demo_feedback_feedback_type ON demo_feedback(feedback_type);
