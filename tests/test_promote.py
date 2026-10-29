from velov.promote import decide


def test_decide_fails_persistence():
    c = {"mae_model": 2.10, "mae_baseline_persistence": 2.00}
    champion = {"mae_model": 2.50}

    promoted, reason = decide(c, champion, min_gain=0.02)
    assert not promoted
    assert "ne bat pas la persistance" in reason


def test_decide_promotes_first_champion():
    """Si aucun champion n'existe encore et que la persistance est battue, on promeut."""
    c = {"mae_model": 1.339, "mae_baseline_persistence": 1.879}
    champion = None

    promoted, reason = decide(c, champion, min_gain=0.02)
    assert promoted
    assert "premier champion" in reason


def test_decide_rejects_insufficient_gain_due_to_noise():
    """Condition 3 : Un gain inférieur à 2 % est considéré comme du bruit lié à la seed."""
    # Champion = 1.339 -> cible à battre = 1.339 * 0.98 = 1.312
    champion = {"mae_model": 1.339}
    # Challenger à 1.325 (gain de ~1 %, insuffisant face au seuil de 2 %)
    c = {"mae_model": 1.325, "mae_baseline_persistence": 1.879}

    promoted, reason = decide(c, champion, min_gain=0.02)
    assert not promoted
    assert "gain insuffisant" in reason


def test_decide_rejects_worse_model():
    """Le challenger est plus mauvais que le champion actuel."""
    champion = {"mae_model": 1.339}
    c = {"mae_model": 1.450, "mae_baseline_persistence": 1.879}

    promoted, reason = decide(c, champion, min_gain=0.02)
    assert not promoted
    assert "gain insuffisant" in reason


def test_decide_promotes_when_gain_reaches_threshold():
    """Le challenger bat le champion d'au moins 2 % et bat la persistance."""
    # Champion = 1.500 -> cible = 1.500 * 0.98 = 1.470
    champion = {"mae_model": 1.500}
    c = {"mae_model": 1.450, "mae_baseline_persistence": 1.879}

    promoted, reason = decide(c, champion, min_gain=0.02)
    assert promoted
    assert "gain sur le champion" in reason
