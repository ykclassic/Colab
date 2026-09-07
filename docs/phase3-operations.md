# Phase 3 operations

- Set `COLAB_MAX_CONCURRENT_WORKSPACES` to bound active product workspaces.
- Set `COLAB_DATABASE_DSN` in the runtime secret store when wiring `PlatformRepository` into the deployment composition root.
- Apply `supabase/migrations/20260907093000_create_phase3_productization_schema.sql` before enabling durable platform persistence.
- Keep browser roles denied on the new tables until authentication and workspace ownership columns are introduced.
- Keep live trading/exchange execution absent from the Phase 3 tool registry.
