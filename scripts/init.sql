-- Initialize Database Schema
CREATE TABLE IF NOT EXISTS extractions (
    id UUID PRIMARY KEY,
    filename TEXT NOT NULL,
    status TEXT NOT NULL,
    data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_extractions_status ON extractions(status);
