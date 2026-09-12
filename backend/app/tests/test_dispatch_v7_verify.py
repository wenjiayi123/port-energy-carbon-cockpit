from app.rl.verify_dispatch_v7 import _weights_match


def test_reference_weights_allow_cross_platform_ulp_drift() -> None:
    expected = [[0.0, -0.5493061443340549]]
    linux_rounding = [[0.0, -0.5493061443340550]]
    materially_different = [[0.0, -0.549306144332]]

    assert _weights_match(expected, linux_rounding)
    assert not _weights_match(expected, materially_different)
