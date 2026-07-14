"""Write recipes, foods, nutrients, variants, and KB into the graph with provenance.

Node and relationship names come from `nectar_contract.names`, never hardcoded, so a contract
schema change is a one-line edit in the shared package. [INVARIANT] Every relationship property
that is a derived (computed, estimated, matched) value carries the DATA_CONTRACT.md Section 1.1
metadata (source, confidence, evidence_tier, computed_by, contract_version) via
`nectar_contract.types.Provenance`. All Cypher is parameterized and lives only in this module.

See DATA_CONTRACT.md Sections 2-3 for the node and relationship shapes, and ../../docs/PDD.md
Section 5 (`nutrition/transform.py`) for how a `Provenance` gets produced upstream of these writers.
"""
from __future__ import annotations

from typing import Any

from nectar_contract import names
from nectar_contract.types import Provenance

from nutriscrape.graph.client import GraphClient
from nutriscrape.nutrition.distribution import DistributionStats
from nutriscrape.knowledge.loaders import DietaryRule, Guideline, Interaction, TransformCoeff


def _provenance_params(provenance: Provenance) -> dict[str, Any]:
    """Flatten a `Provenance` into the metadata fields every derived-value relationship carries
    (DATA_CONTRACT.md Section 1.1)."""
    return {
        "source": provenance.source,
        "confidence": provenance.confidence,
        "evidence_tier": provenance.evidence_tier,
        "computed_by": provenance.computed_by,
        "contract_version": provenance.contract_version,
    }


def merge_dish(
    client: GraphClient,
    *,
    dish_id: str,
    canonical_name: str,
    cluster_confidence: float | None = None,
) -> None:
    """Upsert a `:Dish` (DATA_CONTRACT.md Section 2.1). `cluster_confidence` is set only when
    known; clustering (`clustering/resolve.py`) fills it in once membership is scored."""
    cypher = f"""
    MERGE (d:{names.DISH} {{dish_id: $dish_id}})
    SET d.canonical_name = $canonical_name
    SET d.cluster_confidence = coalesce($cluster_confidence, d.cluster_confidence)
    """
    client.run_write(
        cypher,
        {
            "dish_id": dish_id,
            "canonical_name": canonical_name,
            "cluster_confidence": cluster_confidence,
        },
    )


def merge_recipe(
    client: GraphClient,
    *,
    recipe_id: str,
    title: str,
    source_id: str,
    license: str,
    servings: float,
    confidence: float,
) -> None:
    """Upsert a `:Recipe` (DATA_CONTRACT.md Section 2.1). Does not link it to a `:Dish`; call
    `link_dish_recipe` for that, since clustering may assign or reassign the dish later."""
    cypher = f"""
    MERGE (r:{names.RECIPE} {{recipe_id: $recipe_id}})
    SET r.title = $title,
        r.source_id = $source_id,
        r.license = $license,
        r.servings = $servings,
        r.confidence = $confidence
    """
    client.run_write(
        cypher,
        {
            "recipe_id": recipe_id,
            "title": title,
            "source_id": source_id,
            "license": license,
            "servings": servings,
            "confidence": confidence,
        },
    )


def link_dish_recipe(client: GraphClient, *, dish_id: str, recipe_id: str) -> None:
    """`(:Dish)-[:HAS_VERSION]->(:Recipe)` (DATA_CONTRACT.md Section 3.1). Both nodes must already
    exist; matched by their unique keys, never created here, so this cannot silently fabricate a
    dish or recipe from a typo."""
    cypher = f"""
    MATCH (d:{names.DISH} {{dish_id: $dish_id}})
    MATCH (r:{names.RECIPE} {{recipe_id: $recipe_id}})
    MERGE (d)-[:{names.HAS_VERSION}]->(r)
    """
    client.run_write(cypher, {"dish_id": dish_id, "recipe_id": recipe_id})


def merge_recipe_variant(
    client: GraphClient,
    *,
    variant_id: str,
    is_as_authored: bool,
    confidence: float,
    fluid_ml: float | None = None,
    texture_class: str | None = None,
    glycemic_load: float | None = None,
    serving_mass_g: float | None = None,
    energy_kcal: float | None = None,
) -> None:
    """Upsert a `:RecipeVariant` (DATA_CONTRACT.md Sections 2.1, 3.1). Every recipe must have
    exactly one variant with `is_as_authored = true`; that invariant is enforced by the caller in
    `nutrition/variants.py`, not here."""
    cypher = f"""
    MERGE (v:{names.RECIPE_VARIANT} {{variant_id: $variant_id}})
    SET v.is_as_authored = $is_as_authored,
        v.confidence = $confidence,
        v.fluid_ml = $fluid_ml,
        v.texture_class = $texture_class,
        v.glycemic_load = $glycemic_load,
        v.serving_mass_g = $serving_mass_g,
        v.energy_kcal = $energy_kcal
    """
    client.run_write(
        cypher,
        {
            "variant_id": variant_id,
            "is_as_authored": is_as_authored,
            "confidence": confidence,
            "fluid_ml": fluid_ml,
            "texture_class": texture_class,
            "glycemic_load": glycemic_load,
            "serving_mass_g": serving_mass_g,
            "energy_kcal": energy_kcal,
        },
    )


def link_recipe_variant(client: GraphClient, *, recipe_id: str, variant_id: str) -> None:
    """`(:Recipe)-[:HAS_VARIANT]->(:RecipeVariant)` (DATA_CONTRACT.md Section 3.1)."""
    cypher = f"""
    MATCH (r:{names.RECIPE} {{recipe_id: $recipe_id}})
    MATCH (v:{names.RECIPE_VARIANT} {{variant_id: $variant_id}})
    MERGE (r)-[:{names.HAS_VARIANT}]->(v)
    """
    client.run_write(cypher, {"recipe_id": recipe_id, "variant_id": variant_id})


def merge_food(
    client: GraphClient,
    *,
    fdc_id: str,
    description: str,
    data_type: str,
    source_tier: str,
) -> None:
    """Upsert a `:Food` (DATA_CONTRACT.md Section 2.1), the canonical FDC item resolved by
    `resolution/matcher.py`."""
    cypher = f"""
    MERGE (f:{names.FOOD} {{fdc_id: $fdc_id}})
    SET f.description = $description,
        f.data_type = $data_type,
        f.source_tier = $source_tier
    """
    client.run_write(
        cypher,
        {
            "fdc_id": fdc_id,
            "description": description,
            "data_type": data_type,
            "source_tier": source_tier,
        },
    )


def merge_nutrient(
    client: GraphClient,
    *,
    nutrient_id: str,
    name: str,
    unit: str,
    form: str | None = None,
) -> None:
    """Upsert a `:Nutrient` (DATA_CONTRACT.md Section 2.1). `form` speciates totals (saturated fat,
    added sugar, soluble fiber, and so on) per the contract note under Section 2.1."""
    cypher = f"""
    MERGE (n:{names.NUTRIENT} {{nutrient_id: $nutrient_id}})
    SET n.name = $name,
        n.unit = $unit,
        n.form = $form
    """
    client.run_write(cypher, {"nutrient_id": nutrient_id, "name": name, "unit": unit, "form": form})


def write_contains(
    client: GraphClient,
    *,
    recipe_id: str,
    fdc_id: str,
    raw_mass_g: float,
    prep_id: str | None = None,
) -> None:
    """`(:Recipe)-[:CONTAINS {{raw_mass_g, prep_id}}]->(:Food)` (DATA_CONTRACT.md Section 3.1).
    `raw_mass_g` is the canonical mass (grams, Section 1.2) before any transform is applied."""
    cypher = f"""
    MATCH (r:{names.RECIPE} {{recipe_id: $recipe_id}})
    MATCH (f:{names.FOOD} {{fdc_id: $fdc_id}})
    MERGE (r)-[c:{names.CONTAINS}]->(f)
    SET c.raw_mass_g = $raw_mass_g,
        c.prep_id = $prep_id
    """
    client.run_write(
        cypher,
        {
            "recipe_id": recipe_id,
            "fdc_id": fdc_id,
            "raw_mass_g": raw_mass_g,
            "prep_id": prep_id,
        },
    )


def write_has_nutrient(
    client: GraphClient,
    *,
    variant_id: str,
    nutrient_id: str,
    amount_per_serving: float,
    unit: str,
    provenance: Provenance,
) -> None:
    """`(:RecipeVariant)-[:HAS_NUTRIENT {{amount_per_serving, unit, ...}}]->(:Nutrient)`
    (DATA_CONTRACT.md Section 3.1). This is a cooked, as-eaten value produced by the four-channel
    transform (nutrition/transform.py), so it is a derived value and carries the full Section 1.1
    metadata via `provenance`, not just the illustrative `{{source, confidence}}` shown in the
    contract's relationship sketch."""
    cypher = f"""
    MATCH (v:{names.RECIPE_VARIANT} {{variant_id: $variant_id}})
    MATCH (n:{names.NUTRIENT} {{nutrient_id: $nutrient_id}})
    MERGE (v)-[h:{names.HAS_NUTRIENT}]->(n)
    SET h.amount_per_serving = $amount_per_serving,
        h.unit = $unit,
        h.source = $source,
        h.confidence = $confidence,
        h.evidence_tier = $evidence_tier,
        h.computed_by = $computed_by,
        h.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "variant_id": variant_id,
        "nutrient_id": nutrient_id,
        "amount_per_serving": amount_per_serving,
        "unit": unit,
        **_provenance_params(provenance),
    }
    client.run_write(cypher, params)


def write_has_compound(
    client: GraphClient,
    *,
    variant_id: str,
    compound_id: str,
    provenance: Provenance,
) -> None:
    """`(:RecipeVariant)-[:HAS_COMPOUND]->(:Compound)` (DATA_CONTRACT.md Section 3.1), including
    formation-created compounds (acrylamide, heterocyclic amines) from the transform's formation
    channel."""
    cypher = f"""
    MATCH (v:{names.RECIPE_VARIANT} {{variant_id: $variant_id}})
    MATCH (c:{names.COMPOUND} {{compound_id: $compound_id}})
    MERGE (v)-[h:{names.HAS_COMPOUND}]->(c)
    SET h.source = $source,
        h.confidence = $confidence,
        h.evidence_tier = $evidence_tier,
        h.computed_by = $computed_by,
        h.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "variant_id": variant_id,
        "compound_id": compound_id,
        **_provenance_params(provenance),
    }
    client.run_write(cypher, params)


def write_has_attribute(
    client: GraphClient,
    *,
    variant_id: str,
    attribute_id: str,
    provenance: Provenance,
) -> None:
    """`(:RecipeVariant)-[:HAS_ATTRIBUTE]->(:FoodAttribute)` (DATA_CONTRACT.md Section 3.1),
    prep-resolved tags such as a raw-food flip introduced by cooking."""
    cypher = f"""
    MATCH (v:{names.RECIPE_VARIANT} {{variant_id: $variant_id}})
    MATCH (a:{names.FOOD_ATTRIBUTE} {{attribute_id: $attribute_id}})
    MERGE (v)-[h:{names.HAS_ATTRIBUTE}]->(a)
    SET h.source = $source,
        h.confidence = $confidence,
        h.evidence_tier = $evidence_tier,
        h.computed_by = $computed_by,
        h.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "variant_id": variant_id,
        "attribute_id": attribute_id,
        **_provenance_params(provenance),
    }
    client.run_write(cypher, params)


# ------------------------------------------------------------------------- clinical knowledge base
#
# Writers for the patient-independent clinical knowledge base family (DATA_CONTRACT.md Sections
# 2.2, 3.3, 3.4): the factor nodes (Condition/Medication/Goal/Allergy), DietaryRule, the IMPOSES /
# ACTS_ON / EVIDENCED_BY relationships, drug-food INTERACTS_WITH, the four-channel TRANSFORM edge,
# and Guideline. These take the typed models `knowledge/loaders.py` already validates from
# config/, so a loader change and a writer change stay independently reviewable.

# Contract Section 3.2 names the TRANSFORM edge's left side as `(:Food|:FoodClass)`, but Section
# 2.1's node table only enumerates `:Food`; `:FoodClass` has no entry there yet, so it has no
# constant in `nectar_contract.names`. Kept as a single module constant here, pending a contract
# update that promotes it, rather than a repeated literal.
_FOOD_CLASS_LABEL = "FoodClass"

# Factor labels that may impose a DietaryRule (contract Section 3.3), and the property each is
# keyed by (contract Section 2.2). A whitelist so `link_imposes`'s `factor_label` argument, which
# is caller-supplied rather than a fixed constant, can never be used to interpolate an arbitrary
# label into Cypher.
_FACTOR_ID_FIELD: dict[str, str] = {
    names.CONDITION: "condition_id",
    names.MEDICATION: "medication_id",
    names.GOAL: "goal_id",
    names.ALLERGY: "allergy_id",
    names.PHYSIOLOGIC_STATE: "state_id",
}

# ACTS_ON target labels (contract Section 3.3) and the property each is keyed by. Same whitelist
# purpose as `_FACTOR_ID_FIELD`.
_TARGET_ID_FIELD: dict[str, str] = {
    names.NUTRIENT: "nutrient_id",
    names.FOOD: "fdc_id",
    names.FOOD_ATTRIBUTE: "attribute_id",
    names.COMPOUND: "compound_id",
}

# INTERACTS_WITH may target any of Compound|FoodAttribute|Nutrient|Food (contract Section 3.3),
# and `Interaction.target` (knowledge/loaders.py) does not itself say which. Matched here across
# every candidate id property, same pattern nectar's own `ContractClient` uses for the analogous
# ADDRESSED_BY target lookup ("t.nutrient_id = $target_id OR t.compound_id = $target_id").
_INTERACTION_TARGET_MATCH = (
    "MATCH (t) WHERE t.nutrient_id = $target_id OR t.fdc_id = $target_id "
    "OR t.attribute_id = $target_id OR t.compound_id = $target_id"
)


def merge_condition(
    client: GraphClient,
    *,
    condition_id: str,
    name: str | None = None,
    icd10: str | None = None,
) -> None:
    """Upsert a `:Condition` factor node (DATA_CONTRACT.md Section 2.2). `name`/`icd10` use
    `coalesce` so a later call carrying only `condition_id` (for example, one inferred purely from
    a rule's `rule_id`) never blanks a name already on record."""
    cypher = f"""
    MERGE (c:{names.CONDITION} {{condition_id: $condition_id}})
    SET c.name = coalesce($name, c.name),
        c.icd10 = coalesce($icd10, c.icd10)
    """
    client.run_write(cypher, {"condition_id": condition_id, "name": name, "icd10": icd10})


def merge_medication(
    client: GraphClient,
    *,
    medication_id: str,
    name: str | None = None,
    rxnorm: str | None = None,
) -> None:
    """Upsert a `:Medication` factor node (DATA_CONTRACT.md Section 2.2)."""
    cypher = f"""
    MERGE (m:{names.MEDICATION} {{medication_id: $medication_id}})
    SET m.name = coalesce($name, m.name),
        m.rxnorm = coalesce($rxnorm, m.rxnorm)
    """
    client.run_write(cypher, {"medication_id": medication_id, "name": name, "rxnorm": rxnorm})


def merge_goal(client: GraphClient, *, goal_id: str, name: str | None = None) -> None:
    """Upsert a `:Goal` factor node (DATA_CONTRACT.md Section 2.2)."""
    cypher = f"""
    MERGE (g:{names.GOAL} {{goal_id: $goal_id}})
    SET g.name = coalesce($name, g.name)
    """
    client.run_write(cypher, {"goal_id": goal_id, "name": name})


def merge_allergy(client: GraphClient, *, allergy_id: str, name: str | None = None) -> None:
    """Upsert an `:Allergy` factor node (DATA_CONTRACT.md Section 2.2)."""
    cypher = f"""
    MERGE (a:{names.ALLERGY} {{allergy_id: $allergy_id}})
    SET a.name = coalesce($name, a.name)
    """
    client.run_write(cypher, {"allergy_id": allergy_id, "name": name})


def merge_method(client: GraphClient, *, method_id: str, name: str | None = None) -> None:
    """Upsert a `:Method` reference node (DATA_CONTRACT.md Section 2.1)."""
    cypher = f"""
    MERGE (m:{names.METHOD} {{method_id: $method_id}})
    SET m.name = coalesce($name, m.name)
    """
    client.run_write(cypher, {"method_id": method_id, "name": name})


def merge_dietary_rule(client: GraphClient, *, rule: DietaryRule) -> None:
    """Upsert a `:DietaryRule` (DATA_CONTRACT.md Section 2.2) from a `knowledge.loaders.DietaryRule`.
    A `DietaryRule` is itself curated/derived knowledge (never read verbatim from an authoritative
    source), so its Section 1.1 provenance metadata is carried on the node, not a relationship."""
    cypher = f"""
    MERGE (r:{names.DIETARY_RULE} {{rule_id: $rule_id}})
    SET r.direction = $direction,
        r.severity = $severity,
        r.threshold = $threshold,
        r.unit = $unit,
        r.safety_critical = $safety_critical,
        r.basis = $basis,
        r.source = $source,
        r.confidence = $confidence,
        r.evidence_tier = $evidence_tier,
        r.computed_by = $computed_by,
        r.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "rule_id": rule.rule_id,
        "direction": rule.direction,
        "severity": rule.severity,
        "threshold": rule.threshold,
        "unit": rule.unit,
        "safety_critical": rule.safety_critical,
        "basis": rule.basis,
        **_provenance_params(rule.provenance),
    }
    client.run_write(cypher, params)


def link_imposes(client: GraphClient, *, factor_label: str, factor_id: str, rule_id: str) -> None:
    """`(:Condition|:Medication|:Goal|:Allergy|:PhysiologicState)-[:IMPOSES]->(:DietaryRule)`
    (DATA_CONTRACT.md Section 3.3). `factor_label` must be one of the contract's factor labels (a
    `nectar_contract.names` constant); both endpoints are matched, never created, so a mistyped id
    no-ops rather than fabricating a factor or a rule."""
    id_field = _FACTOR_ID_FIELD.get(factor_label)
    if id_field is None:
        raise ValueError(f"unsupported IMPOSES factor label: {factor_label!r}")
    cypher = f"""
    MATCH (f:{factor_label} {{{id_field}: $factor_id}})
    MATCH (r:{names.DIETARY_RULE} {{rule_id: $rule_id}})
    MERGE (f)-[:{names.IMPOSES}]->(r)
    """
    client.run_write(cypher, {"factor_id": factor_id, "rule_id": rule_id})


def link_acts_on(client: GraphClient, *, rule_id: str, target_id: str, target_label: str) -> None:
    """`(:DietaryRule)-[:ACTS_ON]->(:Nutrient|:Food|:FoodAttribute|:Compound)`
    (DATA_CONTRACT.md Section 3.3). `target_label` must be one of those four contract labels (a
    `nectar_contract.names` constant); both endpoints are matched, never created."""
    id_field = _TARGET_ID_FIELD.get(target_label)
    if id_field is None:
        raise ValueError(f"unsupported ACTS_ON target label: {target_label!r}")
    cypher = f"""
    MATCH (r:{names.DIETARY_RULE} {{rule_id: $rule_id}})
    MATCH (t:{target_label} {{{id_field}: $target_id}})
    MERGE (r)-[:{names.ACTS_ON}]->(t)
    """
    client.run_write(cypher, {"rule_id": rule_id, "target_id": target_id})


def link_evidenced_by(client: GraphClient, *, rule_id: str, guideline_id: str) -> None:
    """`(:DietaryRule)-[:EVIDENCED_BY]->(:Guideline)` (DATA_CONTRACT.md Section 3.3)."""
    cypher = f"""
    MATCH (r:{names.DIETARY_RULE} {{rule_id: $rule_id}})
    MATCH (g:{names.GUIDELINE} {{guideline_id: $guideline_id}})
    MERGE (r)-[:{names.EVIDENCED_BY}]->(g)
    """
    client.run_write(cypher, {"rule_id": rule_id, "guideline_id": guideline_id})


def write_interacts_with(client: GraphClient, *, interaction: Interaction) -> None:
    """`(:Medication)-[:INTERACTS_WITH {{mechanism, effect, severity, direction, threshold, ...}}]
    ->(:Compound|:FoodAttribute|:Nutrient|:Food)` (DATA_CONTRACT.md Section 3.3). The `:Medication`
    endpoint is matched, never created (call `merge_medication` first); the target is matched
    across every candidate id property since `Interaction.target` does not itself say which label
    it is (see `_INTERACTION_TARGET_MATCH`)."""
    cypher = f"""
    MATCH (m:{names.MEDICATION} {{medication_id: $medication_id}})
    {_INTERACTION_TARGET_MATCH}
    MERGE (m)-[i:{names.INTERACTS_WITH}]->(t)
    SET i.mechanism = $mechanism,
        i.effect = $effect,
        i.severity = $severity,
        i.direction = $direction,
        i.threshold = $threshold,
        i.source = $source,
        i.confidence = $confidence,
        i.evidence_tier = $evidence_tier,
        i.computed_by = $computed_by,
        i.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "medication_id": interaction.medication,
        "target_id": interaction.target,
        "mechanism": interaction.mechanism,
        "effect": interaction.effect,
        "severity": interaction.severity,
        "direction": interaction.direction,
        "threshold": interaction.threshold,
        **_provenance_params(interaction.provenance),
    }
    client.run_write(cypher, params)


def _transform_id(coeff: TransformCoeff) -> str:
    """A deterministic natural key for one TRANSFORM edge (food/food-class x method x target x
    channel). The contract does not name an id property for this relationship; this key makes the
    `MERGE` in `write_transform` idempotent across reruns and gives the gated write-back path
    (nectar's `research/verify.py`, DATA_CONTRACT.md Section 8) a stable target to promote."""
    food_key = coeff.food_id or coeff.food_class
    return f"{food_key}:{coeff.method}:{coeff.target}:{coeff.channel}"


def write_transform(client: GraphClient, *, coeff: TransformCoeff) -> None:
    """`(:Food|:FoodClass)-[:TRANSFORM {{target, channel, D, L_base, formation_rate, mechanism,
    ...}}]->(:Method)` (DATA_CONTRACT.md Section 3.2). Merges the `:Method` endpoint
    (`merge_method`), since the knowledge loaders do not separately enumerate methods; the
    `:Food`/`:FoodClass` endpoint must already exist (matched, never created here) -- `:Food` comes
    from `merge_food` in the recipe pipeline, `:FoodClass` from curated knowledge-base data outside
    this module's scope."""
    if coeff.food_id is not None:
        source_label = names.FOOD
        source_key_field = "fdc_id"
        food_key = coeff.food_id
    elif coeff.food_class is not None:
        source_label = _FOOD_CLASS_LABEL
        source_key_field = "food_class"
        food_key = coeff.food_class
    else:
        raise ValueError("TransformCoeff must specify food_id or food_class")

    merge_method(client, method_id=coeff.method)

    cypher = f"""
    MATCH (s:{source_label} {{{source_key_field}: $food_key}})
    MATCH (m:{names.METHOD} {{method_id: $method}})
    MERGE (s)-[t:{names.TRANSFORM} {{transform_id: $transform_id}}]->(m)
    SET t.target = $target,
        t.channel = $channel,
        t.D = $D,
        t.L_base = $L_base,
        t.formation_rate = $formation_rate,
        t.mechanism = $mechanism,
        t.source = $source,
        t.confidence = $confidence,
        t.evidence_tier = $evidence_tier,
        t.computed_by = $computed_by,
        t.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "food_key": food_key,
        "method": coeff.method,
        "transform_id": _transform_id(coeff),
        "target": coeff.target,
        "channel": coeff.channel,
        "D": coeff.D,
        "L_base": coeff.L_base,
        "formation_rate": coeff.formation_rate,
        "mechanism": coeff.mechanism,
        **_provenance_params(coeff.provenance),
    }
    client.run_write(cypher, params)


def merge_guideline(client: GraphClient, *, guideline: Guideline) -> None:
    """Upsert a `:Guideline` (DATA_CONTRACT.md Section 2.2). `chunk` uses `coalesce` because the
    knowledge loaders populate it as a stub (`None`) from the source manifest; a later guideline
    ingest that fills it in should never be blanked by a re-run of the manifest-only loader."""
    cypher = f"""
    MERGE (g:{names.GUIDELINE} {{guideline_id: $guideline_id}})
    SET g.org = $org,
        g.title = $title,
        g.year = $year,
        g.url = $url,
        g.chunk = coalesce($chunk, g.chunk)
    """
    client.run_write(
        cypher,
        {
            "guideline_id": guideline.guideline_id,
            "org": guideline.org,
            "title": guideline.title,
            "year": guideline.year,
            "url": guideline.url,
            "chunk": guideline.chunk,
        },
    )


def merge_preparation(
    client: GraphClient,
    *,
    prep_id: str,
    method: str,
    cut_class: str | None = None,
    water_ratio: float | None = None,
    liquid_retained_frac: float = 1.0,
    time_min: float | None = None,
    temp_c: float | None = None,
) -> None:
    """Upsert a `:Preparation` (DATA_CONTRACT.md Section 2.1): the (method + cut + parameters) an
    ingredient's as-authored preparation carries. `run_ingest` persists this so `run_materialize`
    can re-cook the same food under an alternative method without re-fetching FDC. The CONTAINS edge
    references it by `prep_id`."""
    cypher = f"""
    MERGE (p:{names.PREPARATION} {{prep_id: $prep_id}})
    SET p.method = $method,
        p.cut_class = $cut_class,
        p.water_ratio = $water_ratio,
        p.liquid_retained_frac = $liquid_retained_frac,
        p.time_min = $time_min,
        p.temp_c = $temp_c
    """
    client.run_write(
        cypher,
        {
            "prep_id": prep_id,
            "method": method,
            "cut_class": cut_class,
            "water_ratio": water_ratio,
            "liquid_retained_frac": liquid_retained_frac,
            "time_min": time_min,
            "temp_c": temp_c,
        },
    )


def write_has_nutrient_raw(
    client: GraphClient,
    *,
    fdc_id: str,
    nutrient_id: str,
    amount_per_100g: float,
    provenance: Provenance,
) -> None:
    """`(:Food)-[:HAS_NUTRIENT_RAW {{amount_per_100g, ...}}]->(:Nutrient)` (DATA_CONTRACT.md
    Section 3.2): the food's intrinsic per-100g raw amount, before any preparation transform. Both
    endpoints are matched (never created); call `merge_food`/`merge_nutrient` first. Carries the full
    Section 1.1 provenance since a mapped FDC amount is a derived (matched, unit-converted) value."""
    cypher = f"""
    MATCH (f:{names.FOOD} {{fdc_id: $fdc_id}})
    MATCH (n:{names.NUTRIENT} {{nutrient_id: $nutrient_id}})
    MERGE (f)-[h:{names.HAS_NUTRIENT_RAW}]->(n)
    SET h.amount_per_100g = $amount_per_100g,
        h.source = $source,
        h.confidence = $confidence,
        h.evidence_tier = $evidence_tier,
        h.computed_by = $computed_by,
        h.contract_version = $contract_version
    """
    params: dict[str, Any] = {
        "fdc_id": fdc_id,
        "nutrient_id": nutrient_id,
        "amount_per_100g": amount_per_100g,
        **_provenance_params(provenance),
    }
    client.run_write(cypher, params)


def write_dish_nutrient_stats(
    client: GraphClient, *, dish_id: str, stats: dict[str, DistributionStats]
) -> None:
    """Materialize per-dish nutrient distribution statistics on the `:Dish` node (DATA_CONTRACT.md
    Section 5). Neo4j node properties cannot hold a nested map, so the stats are stored as parallel
    primitive arrays indexed by `stat_nutrient_ids`: for nutrient `stat_nutrient_ids[i]`, its spread
    is `stat_min[i]`/`stat_max[i]`/`stat_mean[i]`/`stat_median[i]`/`stat_stdev[i]` over `stat_count[i]`
    versions. The `:Dish` is matched (never created); cluster's `merge_dish` creates it first."""
    nutrient_ids = sorted(stats)
    cypher = f"""
    MATCH (d:{names.DISH} {{dish_id: $dish_id}})
    SET d.stat_nutrient_ids = $nutrient_ids,
        d.stat_count = $count,
        d.stat_min = $minimum,
        d.stat_max = $maximum,
        d.stat_mean = $mean,
        d.stat_median = $median,
        d.stat_stdev = $stdev
    """
    client.run_write(
        cypher,
        {
            "dish_id": dish_id,
            "nutrient_ids": nutrient_ids,
            "count": [stats[n].count for n in nutrient_ids],
            "minimum": [stats[n].minimum for n in nutrient_ids],
            "maximum": [stats[n].maximum for n in nutrient_ids],
            "mean": [stats[n].mean for n in nutrient_ids],
            "median": [stats[n].median for n in nutrient_ids],
            "stdev": [stats[n].stdev for n in nutrient_ids],
        },
    )
