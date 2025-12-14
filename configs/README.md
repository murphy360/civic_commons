# /configs

City configuration files in YAML format. Each file defines a complete deployment.

## Usage

1. Copy `_template.yaml` to `<your-city>.yaml`
2. Fill in your city's details
3. Configure data sources
4. Restart the worker service

## File Structure

```yaml
city_profile:     # City identity
assistant:        # Bot personality  
sources:          # Public data sources (required)
private_sources:  # Optional/community sources
```

## Adding a New City

```bash
cp _template.yaml mycity.yaml
# Edit mycity.yaml with your city's configuration
docker-compose restart commons-worker
```

The worker automatically loads all YAML files in this directory.
