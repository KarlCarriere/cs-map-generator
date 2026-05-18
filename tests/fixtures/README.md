# Test Fixtures

This directory is reserved for test fixtures committed to the repository.

The current MVP test suite generates synthetic SRTM tiles at fixture-setup time via
`tests/conftest.py` (`srtm_cache_directory` fixture). This keeps the repository small (real SRTM
tiles are ~26 MB each) and reproducible across machines without requiring the test author to
hand-place binary fixtures.

Future committed fixtures (e.g. golden-output baseline hashes, small recorded OSM GraphML
snippets) live here under sub-folders.
