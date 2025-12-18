# Contributing to Civic Commons

Thank you for your interest in contributing to Civic Commons! This guide will help you get started.

## 🚀 Getting Started

### Prerequisites

- **Docker Desktop** - [Download](https://www.docker.com/products/docker-desktop/)
- **Git** - For version control
- **Node.js 20+** - Only if developing web/admin locally without Docker
- **Python 3.12+** - Only if developing scraper/server locally without Docker

### Setup

1. **Fork and clone** the repository:
   ```bash
   git clone https://github.com/YOUR_USERNAME/civic_commons.git
   cd civic_commons
   ```

2. **Follow [QUICKSTART.md](QUICKSTART.md)** to set up your environment and start services.

3. **Verify everything is running:**
   ```bash
   docker compose ps  # All services should show "healthy"
   ```

---

## 📁 Project Structure

```
civic_commons/
├── admin/          # Admin dashboard (Next.js)
├── configs/        # City YAML configurations
├── scraper/        # Worker service (Python)
│   ├── drivers/    # Source-specific scrapers
│   └── pipeline/   # Data processing
├── server/         # API server (Python/FastAPI)
├── shared/         # Shared TypeScript code
├── web/            # Public web app (Next.js)
├── scripts/        # Database scripts
└── tests/          # Test suites
```

---

## 🔧 Development Workflows

### Adding a New Driver

Drivers scrape data from civic websites. To add a new driver:

1. **Copy the template:**
   ```bash
   cp scraper/drivers/_template.py scraper/drivers/your_driver.py
   ```

2. **Implement the `fetch()` method:**
   ```python
   class YourDriver(BaseDriver):
       async def fetch(self) -> tuple[list[Event], list[Document]]:
           # Your scraping logic here
           pass
   ```

3. **Register in `__init__.py`:**
   ```python
   # scraper/drivers/__init__.py
   from .your_driver import YourDriver
   
   DRIVERS = {
       # ... existing drivers
       "your_driver": YourDriver,
   }
   ```

4. **Test locally:**
   ```bash
   docker compose build commons-worker
   docker compose up -d commons-worker
   docker compose logs -f commons-worker
   ```

5. **Add to a city config:**
   ```yaml
   # configs/your_city.yaml
   sources:
     - name: "Your Source"
       driver: "your_driver"
       params:
         url: "https://..."
   ```

### Modifying the Web/Admin Apps

For hot-reload development, see **Development Mode** in [QUICKSTART.md](QUICKSTART.md#development-mode-optional).

Quick version:
```bash
docker compose up db commons-api   # Keep DB and API running
cd web && npm install && npm run dev  # Run web locally with hot reload
```

### Modifying the Scraper/Server

```bash
# Rebuild and restart after changes
docker compose build commons-worker && docker compose up -d commons-worker

# For API server
docker compose build commons-api && docker compose up -d commons-api
```

---

## ✅ Code Standards

### Python (scraper/, server/)

- **Type hints required** on all functions
- **Docstrings** for classes and public functions
- **Max file size**: ~500 lines (split if larger)
- **Formatting**: Black + isort

```python
def process_document(doc: Document, config: dict) -> ProcessedDoc:
    """
    Process a document for storage.
    
    Args:
        doc: The document to process
        config: Processing configuration
        
    Returns:
        Processed document ready for storage
    """
    pass
```

### TypeScript (web/, admin/, shared/)

- **TypeScript strict mode** enabled
- **Functional components** with hooks
- **Server components** where possible (Next.js)
- **Formatting**: Prettier + ESLint

```typescript
interface EventCardProps {
  event: Event;
  onSelect?: (id: number) => void;
}

export function EventCard({ event, onSelect }: EventCardProps) {
  // ...
}
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add calendar export endpoint
fix: correct date parsing in CivicPlus driver
docs: update README with new env vars
refactor: extract shared utilities to civicplus_utils
```

---

## 🧪 Running Tests

### Python Tests

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all tests
pytest tests/

# Run with coverage
pytest --cov=scraper --cov=server tests/

# Run specific test file
pytest tests/scraper/drivers/test_civic_plus.py
```

### TypeScript Tests

```bash
# Web app tests
cd web && npm test

# Admin app tests
cd admin && npm test
```

---

## 📤 Submitting Changes

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/bug-description
```

### 2. Make Your Changes

- Keep commits focused and atomic
- Update documentation if needed
- Add/update tests for new features

### 3. Test Locally

```bash
# Ensure everything builds
docker compose build

# Run the stack
docker compose up -d

# Check health
docker compose ps
```

### 4. Submit a Pull Request

1. Push your branch to your fork
2. Open a PR against `main` branch
3. Fill out the PR template
4. Wait for review

### PR Checklist

- [ ] Code follows project style guidelines
- [ ] Self-reviewed for obvious issues
- [ ] Added tests for new functionality
- [ ] Updated documentation if needed
- [ ] All existing tests pass
- [ ] Docker build succeeds

---

## 🐛 Reporting Issues

### Bug Reports

Please include:
- Steps to reproduce
- Expected vs actual behavior
- Docker logs if applicable (`docker compose logs`)
- Environment details (OS, Docker version)

### Feature Requests

- Check existing issues first
- Reference relevant personas from `/personas/` if applicable
- Describe the use case, not just the solution

---

## 💬 Getting Help

- **GitHub Issues** - For bugs and feature requests
- **GitHub Discussions** - For questions and ideas
- **Code comments** - Add `// TODO:` or `# TODO:` for future work

---

## 📜 License

By contributing, you agree that your contributions will be licensed under the MIT License.

---

## 🙏 Thank You!

Every contribution helps make local government more accessible. Whether it's fixing a typo, adding a driver for your city, or improving documentation - it all matters!
