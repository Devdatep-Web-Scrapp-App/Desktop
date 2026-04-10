# Pasos para convertir el ejecutable de Python a un archivo .exe

## 1. Instalar dependencias
```bash
pip install -r requirements_desktop.txt
```

## 2. Crear el ejecutable
```bash
pyinstaller --onefile --noconsole --name "RRSS_Analytics" --add-data "assets;assets" --icon "assets/logo.ico" app_desktop.py
```

## 3. Reiniciar el explorador para actualizar el icono

- Abrir administrador de tareas (Ctrl + Shift + Esc)
- Buscar "Explorador de Windows" o "Windows Explorer"
- Hacer clic derecho y seleccionar "Reiniciar"