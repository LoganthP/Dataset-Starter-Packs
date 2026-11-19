"""The client token must be byte-identical to the one @vercel/blob's generateClientTokenFromReadWriteToken makes,
otherwise Blob rejects the browser's direct upload. GOLDEN was produced by the official library (see below)."""
from app import blob

RW = "vercel_blob_rw_teststore123_FAKEFAKEFAKEFAKE"  # not a real token
# node: generateClientTokenFromReadWriteToken({ token: RW, pathname: "uploads/x/data.csv", maximumSizeInBytes: 2147483648,
#                                               validUntil: 1900000000000, addRandomSuffix: true })   // @vercel/blob/client
GOLDEN = ("vercel_blob_client_teststore123_OGIzMGM4M2IwNjA5YjVlY2YxNTI0NzViYjJkZWZkZTgyN2QwY2E5NzJhYzMyYWQxNTA0NjgzZjVmNDk3YWViYS5leUp3WVhSb2JtRnRaU0k2SW5Wd2JHOWhaSE12ZUM5a1lYUmhMbU56ZGlJc0ltMWhlR2x0ZFcxVGFYcGxTVzVDZVhSbGN5STZNakUwTnpRNE16WTBPQ3dpZG1Gc2FXUlZiblJwYkNJNk1Ua3dNREF3TURBd01EQXdNQ3dpWVdSa1VtRnVaRzl0VTNWbVptbDRJanAwY25WbGZRPT0=")


def test_token_matches_official_library():
    got = blob.client_token("uploads/x/data.csv", maximum_size_in_bytes=2147483648, valid_until_ms=1900000000000, rw_token=RW)
    assert got == GOLDEN


def test_status_never_contains_the_secret():
    import os
    os.environ["BLOB_READ_WRITE_TOKEN"] = RW
    try:
        s = blob.status()
        assert s["configured"] and s["storeId"] == "teststore123" and "FAKEFAKE" not in str(s)
    finally:
        os.environ.pop("BLOB_READ_WRITE_TOKEN")
