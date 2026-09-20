PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS candidates (
    id TEXT PRIMARY KEY,
    structure_hash TEXT NOT NULL UNIQUE,
    canonical_psmiles TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaigns (
    id TEXT PRIMARY KEY,
    state TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS campaign_candidates (
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    generation INTEGER NOT NULL,
    selected INTEGER NOT NULL DEFAULT 1 CHECK (selected IN (0, 1)),
    PRIMARY KEY (campaign_id, candidate_id, generation)
);

CREATE TABLE IF NOT EXISTS observations (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    property TEXT NOT NULL,
    provenance TEXT NOT NULL,
    protocol_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS observations_candidate_idx ON observations(candidate_id);

CREATE TABLE IF NOT EXISTS predictions (
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    property TEXT NOT NULL,
    model_version TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (candidate_id, property, model_version)
);

CREATE TABLE IF NOT EXISTS physics_jobs (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    candidate_id TEXT NOT NULL REFERENCES candidates(id),
    state TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    campaign_id TEXT NOT NULL REFERENCES campaigns(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
