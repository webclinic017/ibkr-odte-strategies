# Contributing to IBKR 0DTE Strategies 🚀

First off, thank you for considering contributing to IBKR 0DTE Strategies! It's people like you that make this project better for everyone in the quantitative trading community.

## 📋 Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [How Can I Contribute?](#how-can-i-contribute)
- [Development Process](#development-process)
- [Style Guidelines](#style-guidelines)
- [Testing Guidelines](#testing-guidelines)
- [Commit Guidelines](#commit-guidelines)
- [Pull Request Process](#pull-request-process)

## 📜 Code of Conduct

This project adheres to a Code of Conduct. By participating, you are expected to:
- Use welcoming and inclusive language
- Be respectful of differing viewpoints and experiences
- Gracefully accept constructive criticism
- Focus on what is best for the community
- Show empathy towards other community members

## 🚀 Getting Started

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/ibkr-odte-strategies.git
   cd ibkr-odte-strategies
   ```
3. Add the upstream repository:
   ```bash
   git remote add upstream https://github.com/jefrnc/ibkr-odte-strategies.git
   ```
4. Create a virtual environment and install dependencies:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   pip install -r requirements-dev.txt  # If available
   ```

## 💡 How Can I Contribute?

### Reporting Bugs 🐛

Before creating bug reports, please check existing issues. When creating a bug report, include:

- **Clear title and description**
- **Steps to reproduce**
- **Expected behavior**
- **Actual behavior**
- **System information** (OS, Python version, IBKR API version)
- **Relevant logs or error messages**
- **Code snippets** if applicable

### Suggesting Enhancements ✨

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, include:

- **Clear title and description**
- **Use case** - explain why this enhancement would be useful
- **Possible implementation** - if you have ideas on how to implement it
- **Alternative solutions** you've considered

### Contributing Code 💻

#### Areas Where We Need Help

- **New Strategies**: Implementation of new 0DTE strategies
- **Performance Optimization**: Improving execution speed and reducing latency
- **Risk Management**: Enhanced risk controls and position sizing algorithms
- **Backtesting**: Improving backtesting accuracy and features
- **Documentation**: Improving docs, adding examples, fixing typos
- **Testing**: Adding unit tests, integration tests, and test coverage

## 🔄 Development Process

1. **Create a branch** from `main` for your feature/fix:
   ```bash
   git checkout -b feature/your-feature-name
   # or
   git checkout -b fix/issue-number-description
   ```

2. **Make your changes** following the style guidelines

3. **Write/update tests** for your changes

4. **Run tests** to ensure everything passes:
   ```bash
   python -m pytest tests/  # If tests exist
   python -m pylint src/    # Linting
   ```

5. **Commit your changes** following commit guidelines

6. **Push to your fork** and submit a pull request

## 🎨 Style Guidelines

### Python Style Guide

We follow PEP 8 with some modifications:

```python
# Good example
class OptionStrategy:
    """Base class for option trading strategies."""
    
    def __init__(self, symbol: str, expiry: str, strike: float):
        """
        Initialize option strategy.
        
        Args:
            symbol: Trading symbol (e.g., 'SPY')
            expiry: Option expiration date (YYYYMMDD)
            strike: Strike price
        """
        self.symbol = symbol
        self.expiry = expiry
        self.strike = strike
    
    def calculate_greeks(self) -> Dict[str, float]:
        """Calculate option Greeks."""
        # Implementation here
        pass
```

### Key Points:
- **Line length**: 100 characters maximum
- **Imports**: Group in order (standard library, third-party, local)
- **Type hints**: Use type hints for function arguments and returns
- **Docstrings**: Use Google style docstrings
- **Constants**: UPPER_CASE_WITH_UNDERSCORES
- **Protected members**: _single_leading_underscore
- **Private members**: __double_leading_underscore (use sparingly)

### Trading-Specific Guidelines

- **Risk parameters** should always have defaults and validation
- **Position sizing** must include proper bounds checking
- **API calls** should have retry logic and error handling
- **Market data** should be validated for staleness
- **Order placement** must log all actions for audit trail

## 🧪 Testing Guidelines

### Test Structure
```python
# tests/test_strategies.py
import pytest
from src.strategies import ODTEStrategy

class TestODTEStrategy:
    """Test suite for ODTE strategy."""
    
    @pytest.fixture
    def strategy(self):
        """Create strategy instance for testing."""
        return ODTEStrategy('SPY', risk_level=0.02)
    
    def test_position_sizing(self, strategy):
        """Test position sizing calculation."""
        size = strategy.calculate_position_size(10000, 0.02)
        assert size > 0
        assert size <= 200  # Max 2% risk
    
    def test_entry_signal(self, strategy, market_data):
        """Test entry signal generation."""
        signal = strategy.check_entry_signal(market_data)
        assert signal in ['BUY', 'SELL', 'HOLD']
```

### Testing Checklist
- [ ] Unit tests for new functions/methods
- [ ] Integration tests for API interactions
- [ ] Mock external dependencies (IBKR API, market data)
- [ ] Test edge cases and error conditions
- [ ] Verify risk limits are enforced
- [ ] Check for proper logging

## 📝 Commit Guidelines

We follow the Conventional Commits specification:

### Format
```
<type>(<scope>): <subject>

<body>

<footer>
```

### Types
- **feat**: New feature
- **fix**: Bug fix
- **docs**: Documentation changes
- **style**: Code style changes (formatting, missing semicolons, etc.)
- **refactor**: Code refactoring
- **perf**: Performance improvements
- **test**: Adding or updating tests
- **chore**: Maintenance tasks

### Examples
```bash
feat(strategy): add iron condor 0DTE strategy

Implemented new iron condor strategy with dynamic strike selection
based on implied volatility and delta neutral positioning.

Closes #123
```

```bash
fix(risk): correct position sizing calculation for small accounts

Fixed issue where position sizing would exceed account balance
for accounts under $5000.
```

## 🔀 Pull Request Process

1. **Update documentation** for any changed functionality
2. **Add tests** for new features
3. **Ensure all tests pass**
4. **Update README.md** if needed
5. **Fill out the PR template** completely

### PR Template
```markdown
## Description
Brief description of changes

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Breaking change
- [ ] Documentation update

## Testing
- [ ] Unit tests pass
- [ ] Integration tests pass
- [ ] Manual testing completed

## Checklist
- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Comments added for complex code
- [ ] Documentation updated
- [ ] No sensitive data (API keys, passwords) included
- [ ] Risk parameters validated
- [ ] Error handling implemented

## Performance Impact
Description of any performance implications

## Screenshots (if applicable)
Add screenshots of UI changes or strategy performance
```

## 🎯 Performance Considerations

When contributing strategies or optimizations:

1. **Latency**: Aim for < 100ms order execution
2. **Memory**: Avoid storing unnecessary historical data
3. **API Calls**: Minimize and batch when possible
4. **Calculations**: Pre-calculate values when feasible
5. **Threading**: Use appropriate concurrency for market data

## 📚 Additional Resources

- [IBKR API Documentation](https://interactivebrokers.github.io/)
- [Options Theory](https://www.optionseducation.org/)
- [Python Best Practices](https://docs.python-guide.org/)
- [Git Workflow](https://www.atlassian.com/git/tutorials/comparing-workflows)

## 🤝 Getting Help

- **Discord**: [Join our community](https://discord.gg/trading) (if applicable)
- **Issues**: Use GitHub issues for bugs and features
- **Discussions**: Use GitHub Discussions for questions
- **Email**: jsfrnc@gmail.com for sensitive matters

## 📄 License

By contributing, you agree that your contributions will be licensed under the same license as the project (MIT License).

---

Thank you for contributing to IBKR 0DTE Strategies! 🚀📈
