"""Unit tests for presentation: unit conversion, serving standardization, disclaimer."""
from nectar.present.units import convert, mass_g, nutrient_amount, temperature_c, volume_ml
from nectar.present.serving import standardize, serving_factor
from nectar.present.disclaimer import attach, is_measured


def test_mass_us_vs_metric():
    assert mass_g(100.0, "metric").unit == "g"
    assert mass_g(100.0, "us").unit == "oz"
    assert mass_g(2000.0, "metric") .unit == "kg"
    assert mass_g(500.0, "us").unit == "lb"          # 500 g > 16 oz


def test_temperature_scale():
    assert temperature_c(100.0, "C") .value == 100.0
    assert temperature_c(100.0, "F").value == 212.0
    assert temperature_c(0.0, "F").value == 32.0


def test_volume_us_cup_threshold():
    assert volume_ml(250.0, "us").unit == "cup"
    assert volume_ml(15.0, "us").unit == "fl oz"
    assert volume_ml(1500.0, "metric").unit == "L"


def test_convert_passthrough_for_nutrient_mass():
    # mg/mcg nutrient masses are unit-system independent and pass through unchanged
    dv = convert(140.0, "mg", "us", "F")
    assert dv.value == 140.0 and dv.unit == "mg"


def test_nutrient_amount_is_label_style_not_system_converted():
    # a nutrient amount keeps its label unit even for grams (unlike bulk mass, which convert() sends
    # to ounces for US): a nutrition label reads 20 g protein in both systems
    protein = nutrient_amount(20.4567, "g")
    assert protein.unit == "g" and protein.value == 20.46           # rounded, not converted to oz
    assert mass_g(20.0, "us").unit == "oz"                          # bulk mass DOES convert
    potassium = nutrient_amount(377.9, "mg")
    assert potassium.unit == "mg" and potassium.value == 377.9


def test_serving_standardize_scales_nutrients():
    ss = standardize({"potassium": 700.0, "sodium": 300.0}, canonical_serving_mass_g=200.0,
                     target_serving_mass_g=100.0)
    assert ss.factor == 0.5
    assert ss.nutrients["potassium"] == 350.0
    assert ss.nutrients["sodium"] == 150.0


def test_serving_factor_rejects_zero_mass():
    import pytest
    with pytest.raises(ValueError):
        serving_factor(0.0, 100.0)


def test_disclaimer_calculated_vs_measured():
    calc = attach(700.0, "mg", source="transform:retn06", confidence=0.5)
    assert not calc.measured and "not laboratory-measured" in calc.disclaimer
    meas = attach(700.0, "mg", source="lab-measurement-1234", confidence=0.95)
    assert meas.measured and is_measured("assay-x")
