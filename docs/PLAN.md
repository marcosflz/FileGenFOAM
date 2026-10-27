# FileGenFOAM Studio — plan de trabajo

## 1. Visión

Una aplicación de escritorio guiada para preparar, ejecutar y visualizar simulaciones CFD con
OpenFOAM, pensada para que un ingeniero pueda recorrer el flujo completo sin editar archivos a mano:

**Modelo 3D → Mallado → Física → Simulación → Resultados**

El motor CFD es OpenFOAM. El runtime principal es **BlueCFD-Core** en Windows; la app también
detecta OpenFOAM en WSL para desarrollo y CI. La interfaz toma como referencia la experiencia
de Ansys Fluent: barra lateral de flujo de trabajo, panel de propiedades contextual, visor 3D central,
consola de solver y postproceso integrado.

## 2. Decisiones de arquitectura

| Capa | Tecnología | Motivo |
| --- | --- | --- |
| Shell de escritorio | Python + pywebview (WebView2) | Ventana nativa, UI web moderna, sin Electron |
| Interfaz | HTML/CSS/JS + three.js local | Visor 3D ligero, estilo Fluent, cero CDN |
| Backend | Flask en `127.0.0.1` | REST local, simple de empaquetar y testear |
| Geometría / malla | gmsh Python API | CAD paramétrico, grupos físicos nombrados, malla tetra/prism/hex |
| Caso CFD | Generador de diccionarios OpenFOAM | Control total, compatible OF8/2412 y BlueCFD |
| Runtime | Adaptadores BlueCFD / WSL | Detección automática y ejecución aislada |
| Postproceso | VTK (CPU) → JSON → three.js | Contornos y cortes sin depender de ParaView |
| Datos | `project.json` + carpeta de caso OpenFOAM | Portable, inspeccionable, versionable |

No se usa ParaView como requisito. Los resultados del demo se pueden abrir sin tener OpenFOAM
instalado porque el caso incluye su malla y sus campos ya calculados.

## 3. Flujo de usuario

1. **Geometría**: elegir un caso guiado (cavidad, conducto, cilindro, STL), ajustar dimensiones,
   previsualizar el dominio y los patches. Importar STL.
2. **Mallado**: tamaño de elemento, refinamiento, capas límite. gmsh genera `.msh`, `gmshToFoam`
   lo convierte a `constant/polyMesh`, se corrigen tipos de patch (`empty`, `wall`) y se ejecuta
   `checkMesh`.
3. **Física**: solver (transitorio `icoFoam` / estacionario `simpleFoam`), fluido, viscosidad,
   condiciones de contorno por patch y criterios de convergencia.
4. **Simulación**: `checkMesh`, ejecución del solver con log en vivo, residuales, progreso y parada.
5. **Resultados**: selector de tiempo, campo (presión, velocidad, magnitud), corte o superficie,
   escala de color, animación y exportación.

El estado se guarda en cada paso. Si el runtime no está disponible, la app sigue permitiendo
geometría, mallado (archivo `.msh`), previsualización y resultados del demo; solo bloquea la ejecución.

## 4. Estructura del repositorio

```
app.py                     lanzador de escritorio
foamstudio/
  models.py                modelo de proyecto serializable
  presets.py               plantillas y condiciones de contorno
  case_writer.py           diccionarios OpenFOAM (0/, constant/, system/)
  meshing.py               gmsh + gmshToFoam + checkMesh
  runtimes.py              detección BlueCFD/WSL y comandos
  jobs.py                  ejecución asíncrona, log, residuales
  results.py               lectura VTK y serialización para three.js
  api.py                   API REST local
  demo.py                  instalación del caso demo
web/                       UI (index.html, css, js, vendor/three)
examples/lid-driven-cavity caso precalculado que se copia al primer arranque
docs/                      plan, arquitectura, BlueCFD
scripts/                   bootstrap de WSL y prototipos
tests/                     tests de caso, parser y API
```

## 5. Hitos

### M0 — Base (completado al inicio del desarrollo)
- Entorno uv + pywebview/WebView2, estructura del repo y plan.

### M1 — Núcleo OpenFOAM
- Modelo de proyecto.
- Generador de `0/U`, `0/p`, `constant/transportProperties`, `constant/turbulenceProperties`,
  `system/controlDict`, `fvSchemes`, `fvSolution`.
- Validación sintáctica y ejecución de un caso cavidad con `icoFoam`.

### M2 — Geometría y mallado
- gmsh: cavidad 2D extruida, conducto, cilindro en cruz.
- Patches nombrados y tipos correctos.
- `gmshToFoam`, `checkMesh`, extracción de métricas y preview de malla.

### M3 — Shell de escritorio
- Ventana pywebview, servidor local.
- Barra lateral de 5 pasos, panel contextual, visor three.js, consola y gráfica de residuales.
- Persistencia, detección de runtime y estados vacíos.

### M4 — Ejecución
- Job manager con hilos, streaming de log, parser de residuales, parada.
- Progreso, errores de OpenFOAM legibles, `checkMesh`.

### M5 — Postproceso
- Lector VTK de OpenFOAM, cortes y superficies, colormap, selector de tiempo.
- Animación y exportación de imagen.

### M6 — MVP demostrable
- Caso cavidad precalculado incluido.
- Ejecución real verificada con OpenFOAM 2412 en WSL.
- Guía de instalación de BlueCFD y tests.
- QA visual y de flujo completo.

## 6. Agent swarm

El desarrollo se dividió en carriles independientes coordinados por el agente principal:

| Agente | Carril | Entregable |
| --- | --- | --- |
| Arquitecto (principal) | Modelo, API, UI, integración y QA | App completa, demo y tests |
| Runtime research | BlueCFD-Core | `docs/BLUECFD.md` + `scripts/probe_bluecfd.py` |
| Meshing | gmsh | Prototipo de mallas, grupos físicos y notas de integración |

Los contratos entre carriles son el modelo `project.json`, la API REST y el formato JSON del visor.
La verificación end-to-end (crear → mallar → simular → postprocesar) y las capturas se hicieron con
Playwright sobre Edge/WebView2 y con `pytest`.

## 7. Criterios de aceptación del MVP

- [x] Se abre una ventana de escritorio con la UI de flujo de trabajo.
- [x] Se puede crear/elegir un proyecto y ver la geometría en 3D.
- [x] Se puede generar una malla y ver su recuento de celdas y patches.
- [x] Se puede configurar fluido, solver y condiciones de contorno.
- [x] Se ejecuta una simulación real de OpenFOAM desde la app, con log y residuales en vivo.
- [x] Se visualizan presión y velocidad en un corte, con selector de tiempo.
- [x] El demo de cavidad funciona sin instalar OpenFOAM (resultados incluidos).
- [x] La app detecta BlueCFD y, si no está, explica cómo instalarlo.
- [x] Tests unitarios y de API pasan.

### Verificación realizada en esta iteración

- Cavidad 2D (`icoFoam`, 6.400 celdas): malla `blockMesh`, 101 pasos, 11 muestras, campos `p`/`U` leídos con VTK.
- Conducto 2D (`simpleFoam`, 6.250 celdas): convergencia hasta el criterio de residuales, resultados y cortes.
- Cilindro 2D (`icoFoam`, 12.696 celdas): malla gmsh con refinamiento, grupos `inlet`/`outlet`/`walls`/`cylinderWall`/`frontAndBack`, `checkMesh` OK.
- Runtime de desarrollo: OpenFOAM 2412 en WSL mediante micromamba.
- BlueCFD-Core 2020-1 (OpenFOAM 8) instalado y validado en Windows: `blockMesh`, `icoFoam` (cavidad, 6.400 celdas, 11 muestras) y `simpleFoam` (conducto, 1.000 celdas) terminan con código 0 y los resultados se leen con VTK.
- Los adaptadores BlueCFD-Core 2020 (OpenFOAM 8) y 2024 (OpenFOAM 12, `foamRun`) están implementados; la ruta de 2024 sigue pendiente de validación en una instalación real.

## 8. Roadmap posterior al MVP

- Turbulencia k-ω SST con funciones de pared y estimación de y+.
- snappyHexMesh para STL complejos y capas límite.
- Fuerzas y coeficientes (Cd/Cl), líneas de corriente y vectores.
- Casos multifase (interFoam) y transferencia de calor (chtMultiRegionFoam).
- Batch de parámetros y comparación de casos.
- Empaquetado firmado (PyInstaller/MSIX) y autoactualización.
- Exportación de informe PDF con imágenes, malla, BCs y residuales.
