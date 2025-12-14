# /tests

Test suites for all Civic Commons services.

## Structure

```
/tests
├── scraper/               # Scraper service tests
│   ├── conftest.py        # Pytest fixtures
│   ├── test_drivers/      # Driver tests
│   └── test_pipeline/     # Pipeline tests
├── server/                # MCP server tests
│   ├── conftest.py        # Pytest fixtures
│   └── test_tools/        # MCP tool tests
├── web/                   # Web app tests (Vitest)
│   └── components/        # Component tests
├── admin/                 # Admin app tests (Vitest)
│   └── components/        # Component tests
└── integration/           # End-to-end tests
    └── test_e2e.py        # Integration tests
```

## Running Tests

### Python Tests (scraper, server)

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-cov

# Run all Python tests
pytest tests/scraper tests/server

# Run with coverage
pytest --cov=scraper --cov=server tests/

# Run specific test file
pytest tests/scraper/test_drivers/test_civic_plus.py
```

### TypeScript Tests (web, admin)

```bash
# Install dependencies
cd web && npm install
cd admin && npm install

# Run web tests
cd web && npm test

# Run admin tests
cd admin && npm test
```

### Integration Tests

```bash
# Start services
docker-compose up -d

# Run integration tests
pytest tests/integration/

# Cleanup
docker-compose down
```

## Writing Tests

### Python Tests

Use pytest with async support:

```python
import pytest
from scraper.drivers.civic_plus import CivicPlusDriver

@pytest.mark.asyncio
async def test_driver_fetch():
    driver = CivicPlusDriver(config)
    result = await driver.fetch()
    assert result.success
```

### TypeScript Tests

Use Vitest with React Testing Library:

```typescript
import { render, screen } from '@testing-library/react';
import { EventCard } from '@/components/features/event-card';

test('renders event title', () => {
  render(<EventCard event={mockEvent} />);
  expect(screen.getByText('City Council Meeting')).toBeInTheDocument();
});
```

## Test Data

Test fixtures and mock data are stored in:
- `tests/fixtures/` - Shared test data
- `tests/mocks/` - Mock responses for external APIs
