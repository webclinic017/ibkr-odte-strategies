# ODTE IBKR Strategies

Un framework modular para desarrollar, probar y ejecutar estrategias de trading de opciones 0DTE (Zero Days To Expiration) utilizando la API de Interactive Brokers (IBKR). Diseñado para facilitar la iteración rápida de estrategias, backtesting y análisis de rendimiento.

## ⚠️ Descargo de Responsabilidad ⚠️

> Este software es exclusivamente para fines **educativos y experimentales**. El trading de opciones conlleva riesgos significativos de pérdida financiera. Nunca uses este código con capital real sin entender completamente su funcionamiento y riesgos. El autor no asume ninguna responsabilidad por pérdidas financieras derivadas del uso de este software.

## Características

- **Arquitectura modular**: Framework extensible para múltiples estrategias
- **Conexión IBKR**: Interfaz simplificada con la API de Interactive Brokers
- **Backtesting integrado**: Validación de estrategias con datos históricos
- **Análisis de rendimiento**: Métricas detalladas y visualizaciones
- **Estrategias incluidas**: 
  - ODTE Breakout: Opera breakouts en opciones 0DTE
  - Earnings Straddle: Estrategia de straddle para earnings

## Configuración Inicial

1. Clonar el repositorio
2. Instalar dependencias:
```bash
pip install -r requirements.txt
```
3. Inicializar archivos de configuración:
```bash
python run_strategy.py init
```
4. **Importante**: Editar los archivos en `config/` para incluir tus claves API y parámetros de trading.

## Uso Rápido

### Configuración de Paper Trading

1. Abre TWS (Trader Workstation) o IB Gateway
2. Activa API en Configuración > API > Habilitar API
3. Conéctate con tu cuenta Paper Trading
4. Ejecuta una estrategia:
```bash
python run_strategy.py run odte_breakout
```

### Backtesting

```bash
python run_strategy.py backtest odte_breakout --start-date 2023-01-01 --end-date 2023-06-30
```

## Estructura del Proyecto

```
odte-ibkr-strats/
├── config/                   # Archivos de configuración
├── src/
│   ├── backtesting/          # Motor de backtesting
│   ├── core/                 # Componentes centrales
│   ├── strategies/           # Estrategias implementadas
│   └── utils/                # Utilidades generales
├── run_strategy.py           # Script principal para ejecutar estrategias
```

## Requisitos

- Python 3.7+
- IB Insync
- Pandas
- Matplotlib
- Requests

## Seguridad

- **NO** commits tus archivos de configuración con API keys
- Usa **SOLO** paper trading mientras pruebas
- Revisa `.gitignore` para asegurar que archivos sensibles no se compartan
- Nunca dejes trading automatizado sin supervisión

## Estrategias Disponibles

### ODTE Breakout

Opera breakouts de precio en opciones que expiran el mismo día, utilizando filtros técnicos.

```bash
python run_strategy.py run odte_breakout
```

### Earnings Straddle

Abre posiciones straddle antes de reportes de ganancias y cierra después del movimiento.

```bash
python run_strategy.py run earnings_straddle
```

## Desarrollo de Nuevas Estrategias

Para crear tu propia estrategia:

1. Extiende la clase base `StrategyBase` en un nuevo archivo en `src/strategies/`
2. Implementa los métodos requeridos:
   - `scan_for_opportunities()`
   - `execute_trade()`
   - `manage_positions()`
3. Actualiza `run_strategy.py` para incluir tu estrategia

## Contribuciones

Las contribuciones son bienvenidas. Por favor, asegúrate de que tu código no contiene información sensible antes de enviar un pull request.

## Licencia

MIT