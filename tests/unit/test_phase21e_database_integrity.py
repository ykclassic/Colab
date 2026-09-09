from pathlib import Path


def test_phase21e_migration_is_workspace_scoped_and_immutable() -> None:
    migration = Path("supabase/migrations/20260909160000_phase21e_quant_research_vertical_slice.sql").read_text()
    assert "workspace_id uuid NOT NULL" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration
    assert "is_workspace_member(workspace_id)" in migration
    assert "immutable" in migration
    assert "REVOKE ALL ON public.quant_research_runs FROM anon" in migration


def test_quant_vertical_slice_modules_exist() -> None:
    assert Path("src/colab/quant_vertical_slice.py").exists()
    assert Path("src/colab/quant_validation.py").exists()
    assert Path("src/colab/quant_vertical_persistence.py").exists()
