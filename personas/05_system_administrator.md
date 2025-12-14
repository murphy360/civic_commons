# Persona: The System Administrator

## Profile
**Name:** Derek Okonkwo  
**Age:** 34  
**Occupation:** IT Manager for a small municipality (not Twinsburg, but considering deploying this for his city)  
**Tech Comfort:** Expert — manages servers, Docker, databases  
**Time Available:** Moderate — would implement this as a side project initially

## Backstory
Derek manages IT for a city of 15,000 in a neighboring county. His city manager heard about Civic Commons and asked him to evaluate it. Derek is excited about the open-source aspect but skeptical about maintenance burden. He's been burned by projects that are easy to demo but hard to operate.

## Primary Use Cases

### 1. "Can I actually deploy this?"
- Evaluates Docker Compose setup
- Checks resource requirements (RAM, CPU, storage)
- Assesses security posture

### 2. "What breaks and how do I fix it?"
- Error handling and logging
- Monitoring and alerting
- Recovery procedures

### 3. "How do I customize for my city?"
- YAML configuration review
- Adding new drivers for local sources
- Theming/branding for his city

### 4. "What's the ongoing maintenance?"
- Driver updates when source websites change
- Database backups and retention
- Dependency updates and security patches

## Pain Points with Typical Open Source Projects
- "README says 'docker-compose up' but reality is 47 undocumented steps"
- "Works on the creator's machine, breaks everywhere else"
- "No logging, no monitoring, no idea when things break"
- "Original maintainer disappears after 6 months"

## What Would Delight Derek
- One-command deployment that actually works
- Comprehensive logging with clear error messages
- Health check endpoints for monitoring
- Clear documentation for adding new drivers
- Active maintenance and responsive to issues

## Feedback on Current Design

### 👍 Likes
- Docker Compose architecture — standard, understandable
- YAML configuration — easy to customize
- Health endpoints mentioned
- Driver pattern — can add sources without core changes
- PostgreSQL — known quantity, easy to backup

### 👎 Concerns
- 5 services seems like a lot — is resource usage reasonable?
- Playwright in Docker is notoriously tricky
- No mention of secrets management (DB passwords, API keys)
- What happens when a city website redesigns and breaks the driver?
- Who maintains drivers for common civic software?

### 💡 Suggestions
- Add resource requirements to documentation (min RAM, CPU)
- Include example docker-compose.override.yml for production settings
- Document secrets management (env files, Docker secrets)
- Add driver test mode: "Does this config work?" without full scrape
- Create driver health dashboard in admin
- Publish Docker images to registry (don't require local build)
- Include sample Prometheus/Grafana configs

## Key Questions for This Persona
1. What are the minimum system requirements?
2. How are secrets (DB password, API keys) managed?
3. Is there a test mode to validate configuration?
4. What's the upgrade path when a new version releases?
5. Who fixes drivers when source websites change?
