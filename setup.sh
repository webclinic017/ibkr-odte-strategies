#!/bin/bash
# Script para configurar el entorno de desarrollo

# Crear entorno virtual
echo "Creando entorno virtual..."
python3 -m venv venv

# Activar entorno
source venv/bin/activate

# Instalar dependencias
echo "Instalando dependencias..."
pip install -r requirements.txt

# Inicializar configuración
echo "Inicializando configuración..."
python run_strategy.py init

echo "Configuración completada. Recuerda editar los archivos en config/ con tus API keys."
echo "Para activar el entorno, ejecuta: source venv/bin/activate"