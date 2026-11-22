/** Source types accepted by taffee-ingest and the ingestion service. Only "code" is implemented today. */
export const SOURCE_TYPES = ['code', 'docs', 'tables', 'logs', 'pdf', 'unknown'] as const;
export type SourceType = (typeof SOURCE_TYPES)[number];
