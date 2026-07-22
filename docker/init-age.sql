-- Runs on first container start (docker-entrypoint-initdb.d).
-- Boots the AGE extension and creates the default graph if it doesn't exist.
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- create_graph() has no IF NOT EXISTS clause and raises if the graph exists,
-- so guard it with an exception handler. (Mostly relevant if this script is
-- re-run against a persisted volume; on a fresh DB it always creates.)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'kg_graph'
    ) THEN
        PERFORM ag_catalog.create_graph('kg_graph');
        RAISE NOTICE 'Created graph kg_graph';
    ELSE
        RAISE NOTICE 'Graph kg_graph already exists';
    END IF;
END $$;

-- Fresh sessions still need LOAD + search_path set at runtime; the app sets
-- these on every connection. This just establishes the baseline.
SET search_path = "$user", public;
