# Lineamientos de Audio y DSP — WaveAI Studio

Este documento define las reglas de estricto cumplimiento para el manejo de audio en el navegador (Web Audio API) y la interacción con el backend DSP de Python.

---

## 1. Principio Fundamental: "Neutral = Bypass"
- Si un control o parámetro está en neutral (ej. perillas en 0, sin EQ aplicada, sin saturación), el resultado de audio debe ser **bit-exacto** respecto al audio original.
- El procesamiento nunca debe colorear o alterar la señal a menos que el usuario o el preset lo indiquen explícitamente.

---

## 2. Web Audio API y Suavizado Anti-Zipper
1. **Sin Saltos Abruptos de Ganancia**:
   - Nunca asignar valores directos a propiedades `gain.value` o frecuencias de corte en caliente (`node.gain.value = x`).
   - Usar siempre rampas exponenciales o lineales suaves para evitar clics acústicos ("zipper noise"):
     ```ts
     node.gain.setTargetAtTime(targetValue, audioCtx.currentTime, 0.02);
     ```
2. **Ciclo de Vida de `AudioContext`**:
   - Respetar las políticas de autoplay de navegadores (iniciar o reanudar el contexto tras la primera interacción del usuario: clic o play).
   - Cerrar o suspender contextos no utilizados para prevenir fugas de memoria y uso innecesario de CPU.

---

## 3. Reproductor A/B Sincronizado
1. **Transporte Sincronizado al Milisegundo**:
   - La alternancia entre la señal Original y la señal Masterizada debe ser instantánea y mantener exactamente la misma posición de tiempo en ambas fuentes.
   - Prohibido desfasar el transporte o reiniciar la pista al conmutar entre A y B.
2. **Normalización y Comparación Justa**:
   - Las comparaciones deben permitir evaluar las mejoras dinámicas, tímbricas y espaciales sin sesgo por mera diferencia de volumen.

---

## 4. Resiliencia y Manejo de Errores DSP
1. **Verificación de Clipping y Calidad**:
   - Monitoreo continuo de True Peak (`dBTP`) y sonoridad integrada (`LUFS`).
   - El sistema debe prevenir clipping por encima de `-0.3 dBTP` en exportaciones para streaming.
2. **Degradación Elegante**:
   - Si el servicio Python o el worker DSP arroja un fallo, la interfaz debe notificar claramente al usuario en su idioma sin perder el borrador ni reiniciar la sesión del proyecto.
