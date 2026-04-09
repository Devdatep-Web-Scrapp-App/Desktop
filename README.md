# Pasos para convertir el ejecutable de Python a un archivo .exe

## 1. Ofuscar el código con PyArmor antes de compilar
PyArmor encripta el bytecode y agrega una capa basica de proteccion anti-reverse:
```bash
pip install pyarmor pyinstaller
```
```bash
pyarmor gen app_desktop.py
```
### El código ofuscado queda en dist/pyarmor/

## 2. Compilar el código ofuscado con PyInstaller
```bash
pyinstaller --onefile --windowed --name "RRSS_Analytics" --collect-all customtkinter --hidden-import selenium --hidden-import schedule --hidden-import requests app_desktop.py
```
--onefile — todo en un solo .exe
--windowed — sin ventana de consola al abrir

## 3. Incluir los archivos necesarios
El exe necesita empaquetar las dependencias de Chrome correctamente:
```bash
pyinstaller --onefile --windowed \
    --name "RRSS_Analytics" \
    --hidden-import customtkinter \
    --hidden-import selenium \
    --hidden-import schedule \
    --collect-all customtkinter \
    app_desktop.py
```