"""The presentation bundle must not include raw agent transcripts."""

import zipfile

from trust.review import package_stage as stage


def test_stage_package_uses_public_allowlist(tmp_path):
    out = tmp_path / "stage.zip"
    stage.package(out)
    with zipfile.ZipFile(out) as z:
        assert set(z.namelist()) == set(stage.ALLOWLIST)
        assert not any("capsule" in name or "session" in name
                       for name in z.namelist())
