// Neo4j ENTERPRISE only. Run once as admin (cypher-shell -u neo4j -p <admin>).
// Passwords here MUST match the podman secrets of the same purpose.
// Community edition has no multi-user RBAC; see README for the fallback.

// --- users ---
CREATE USER nutriscrape_writer SET PASSWORD '<writer_pass>' CHANGE NOT REQUIRED;
CREATE USER nectar_reader      SET PASSWORD '<reader_pass>' CHANGE NOT REQUIRED;
CREATE USER promotion_writer   SET PASSWORD '<promo_pass>'  CHANGE NOT REQUIRED;

// --- NECTAR API: read everything, write nothing ---
CREATE ROLE nectar_read;
GRANT ROLE nectar_read TO nectar_reader;
GRANT ACCESS ON DATABASE neo4j TO nectar_read;
GRANT MATCH {*} ON GRAPH neo4j TO nectar_read;

// --- NutriScrape: full write (builds the graph) ---
CREATE ROLE ingest_write;
GRANT ROLE ingest_write TO nutriscrape_writer;
GRANT ACCESS ON DATABASE neo4j TO ingest_write;
GRANT MATCH {*} ON GRAPH neo4j TO ingest_write;
GRANT WRITE ON GRAPH neo4j TO ingest_write;

// --- Writeback: read, plus the ONLY gated write in the platform ---
// Fine-grained: may set evidence_tier/status on transform-family items and
// create audit nodes. Cannot touch recipes, rules, or interactions.
CREATE ROLE promote_write;
GRANT ROLE promote_write TO promotion_writer;
GRANT ACCESS ON DATABASE neo4j TO promote_write;
GRANT MATCH {*} ON GRAPH neo4j TO promote_write;
GRANT SET PROPERTY {evidence_tier, status} ON GRAPH neo4j NODES HypothesisTransform TO promote_write;
GRANT SET PROPERTY {evidence_tier, status} ON GRAPH neo4j RELATIONSHIPS TRANSFORM TO promote_write;
GRANT CREATE ON GRAPH neo4j NODES PromotionAudit TO promote_write;
// Verify fine-grained SET PROPERTY syntax against your Neo4j 5.x point release.
