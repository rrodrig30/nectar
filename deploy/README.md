# NECTAR Platform: Podman Deployment

Rootless, single-host. Ollama is the default LLM backend; Anthropic or OpenAI can be turned on later without a rebuild. Schema: [`../contract/DATA_CONTRACT.md`](../contract/DATA_CONTRACT.md).

## What runs

Long-lived services: `neo4j`, `ollama`, `nectar-api`, `nectar-web`, `nectar-writeback`, `caddy`.
Run-to-completion batch: `nutriscrape` (triggered, not enabled at boot).

The read/write split from the data contract is enforced by Neo4j roles: `nectar-api` connects as a read-only user, `nutriscrape` as a full writer, and `nectar-writeback` as a role that may only set `evidence_tier`/`status` on transform-family items. See `neo4j/init-roles.cypher`.

## Host prerequisites (one time)

```bash
# Rootless services survive logout / start at boot
loginctl enable-linger "$USER"

# GPU for Ollama, via the Container Device Interface
sudo dnf install -y nvidia-container-toolkit          # or apt
sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml
podman run --rm --device nvidia.com/gpu=all docker.io/library/ubuntu nvidia-smi   # verify

# Let rootless Caddy bind 80/443 (simplest option)
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/50-nectar.conf
sudo sysctl --system
# Alternative: keep the floor high and redirect 443 with firewalld.
```

If the host runs SELinux, the `:Z` labels on the volume mounts in the units handle relabeling.

## Secrets (never in files or images)

```bash
printf 'neo4j/CHANGE_ADMIN'      | podman secret create neo4j_auth -
printf 'CHANGE_READER'           | podman secret create nectar_reader_pass -
printf 'CHANGE_WRITER'           | podman secret create nutriscrape_pass -
printf 'CHANGE_PROMO'            | podman secret create promotion_pass -
```
The reader/writer/promo passwords must match the ones set in `neo4j/init-roles.cypher`.

## Build the images (context is the repo root)

```bash
cd ..    # repo root
podman build -t localhost/nutriscrape:latest -f nutriscrape/Containerfile .
podman build -t localhost/nectar-api:latest  -f nectar/Containerfile .
podman build -t localhost/nectar-web:latest  -f nectar/web/Containerfile .
```

## Install and start

```bash
mkdir -p ~/.config/nectar ~/.config/containers/systemd
cp deploy/env/platform.env.example ~/.config/nectar/platform.env   # edit domain, models
cp deploy/caddy/Caddyfile          ~/.config/nectar/Caddyfile      # set your Ionos domain
cp deploy/quadlet/*                ~/.config/containers/systemd/

systemctl --user daemon-reload
systemctl --user start neo4j
# create roles once Neo4j is healthy (Enterprise):
podman exec -i neo4j cypher-shell -u neo4j -p CHANGE_ADMIN < deploy/neo4j/init-roles.cypher
systemctl --user start ollama nectar-web nectar-api nectar-writeback caddy

# pull the models named in platform.env
podman exec ollama ollama pull llama3.1:8b
podman exec ollama ollama pull llama3.2:3b
```

### Stage the input data (one time)

Set the batch inputs in `~/.config/nectar/platform.env` (`NUTRISCRAPE_CORPUS`, `FDC_BULK_DIR`,
`NUTRISCRAPE_MAX_PARALLEL`), then drop the data into the named volumes those paths point at:

```bash
# recipe corpus (RecipeNLG CSV, or a .txt/.urls list of schema.org URLs) -> corpus-staging (/data)
podman volume import corpus-staging recipes_full.csv     # or copy into the volume mount
# USDA FDC CSV bulk export (food.csv, nutrient.csv, food_nutrient.csv) -> fdc-staging (/fdc)
#   download + extract from https://fdc.nal.usda.gov/download-datasets
```

With `FDC_BULK_DIR` staged, `fdc-import` loads food composition into the graph and ingest resolves
foods locally, so no `FDC_API_KEY` is needed. Without it, set `fdc_api_key` as a podman secret
(see `platform.env.example`) and ingest falls back to the FDC API.

### Run the batch pipeline (it exits on completion)

```bash
# parallel Prefect DAG: schema -> knowledge -> fdc-import -> parallel ingest -> cluster -> materialize
systemctl --user start nutriscrape-flow

# or the sequential single-process path:
systemctl --user start nutriscrape                 # run-all

# or a single stage:
podman run --rm --network nectar --env-file ~/.config/nectar/platform.env \
  -e NEO4J_URI=bolt://neo4j:7687 -e NEO4J_USER=nutriscrape_writer \
  --secret nutriscrape_pass,type=env,target=NEO4J_PASSWORD \
  -v corpus-staging:/data:Z -v fdc-staging:/fdc:Z localhost/nutriscrape:latest fdc-import
```

## Turning on Anthropic or OpenAI later

No rebuild. In `~/.config/nectar/platform.env` set `LLM_BACKEND=anthropic` (or `openai`) and the model, then:
```bash
printf 'sk-...' | podman secret create llm_api_key -
# add to nectar-api.container (and nutriscrape.container if it generates text):
#   Secret=llm_api_key,type=env,target=LLM_API_KEY
systemctl --user daemon-reload
systemctl --user restart nectar-api nutriscrape
systemctl --user disable --now ollama          # optional, frees the GPU
```
The app's LLM interface selects the client from `LLM_BACKEND`, so only config and a secret change.

## Neo4j Community fallback

Community edition has no multi-user RBAC. If you use it, skip `init-roles.cypher` and point all services at the single `neo4j` user. The read/write split is then enforced at the app and network layer, not the database, which is weaker; the writeback service being the only container with write logic is your remaining guard. Enterprise (eval/dev license) is recommended so the split is enforced where it cannot be bypassed.

## Operational notes

- Back up the `neo4j-data` volume. It is the knowledge asset; nothing else is precious.
- Size `corpus-staging` for tens of GB. RecipeNLG is >2 GB, and the FDC and Open Food Facts full exports are several GB each before intermediates.
- Tune Neo4j heap and pagecache in `neo4j.container` to the host; the vector index is memory-hungry at recipe scale.
- Regenerate the CDI spec (`nvidia-ctk cdi generate`) after NVIDIA driver updates, or Ollama loses the GPU.
- Verify the fine-grained `SET PROPERTY` grant syntax against your exact Neo4j 5.x point release before relying on it.
