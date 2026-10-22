# Guía de Rotación de Credenciales R2 (Cloudflare)
> **Objetivo:** Generar nuevas claves, validarlas localmente, actualizar Railway y revocar las antiguas **sin downtime**.

---

## 1. Generar nuevo par de claves en Cloudflare R2

1. Entra a **Cloudflare Dashboard** → **R2 Object Storage** → **Manage R2 API tokens**
2. Click **Create API token** → **Custom token**
3. Configura:
   - **Token name:** `audiomind-backend-rotated-<fecha>` (ej. `audiomind-backend-rotated-2026-10-22`)
   - **Permissions:** `Object Read & Write` (o `Object Read` + `Object Write` por separado)
   - **Bucket resources:** Selecciona **tu bucket específico** (no "All buckets") — ej. `waveia-audio`
   - **Account resources:** `Account Settings` → `Read` (opcional, para listar buckets)
   - **TTL:** `90 days` (o el que prefieras; márcalo en calendario para próxima rotación)
4. Click **Continue to summary** → **Create token**
5. **COPIA Y GUARDA INMEDIATAMENTE:**
   - `Access Key ID` (empieza con `...`)
   - `Secret Access Key` (solo se muestra **una vez**)

> ⚠️ Si pierdes el Secret, debes repetir el proceso. No hay "ver de nuevo".

---

## 2. Validar claves nuevas ANTES de tocar producción

Usa el script de verificación incluido:

```bash
# Desde la raíz del repo
cd C:\Users\brik3\Desktop\BrikMaster2027

# Setea las NUEVAS credenciales como variables de entorno (NO las commits)
$env:AUDIOMIND_R2_ENDPOINT="https://<account-id>.r2.cloudflarestorage.com"
$env:AUDIOMIND_R2_ACCESS_KEY_ID="<NUEVO_ACCESS_KEY>"
$env:AUDIOMIND_R2_SECRET_ACCESS_KEY="<NUEVO_SECRET_KEY>"
$env:AUDIOMIND_R2_BUCKET="<nombre-de-tu-bucket>"

# Ejecuta el test (sube 1 byte, lista, borra)
python scripts/verify_r2_keys.py
```

**Salida esperada (éxito):**
```
✅ Conexión R2 OK (endpoint: https://xxx.r2.cloudflarestorage.com)
✅ Bucket 'waveia-audio' accesible
✅ Subida test-object (1 byte) OK
✅ Listado objetos OK
✅ Borrado test-object OK
🎉 Credenciales NUEVAS validadas correctamente
```

Si falla → **no actualices Railway**. Revisa endpoint, bucket name, permisos del token.

---

## 3. Actualizar Railway (backend service) — **Sin reiniciar el servicio manualmente**

> Railway aplica env vars y **reinicia automáticamente** el deployment. El proceso es atómico.

1. Entra a **Railway Dashboard** → Proyecto `WaveIA` (o `Brik`) → Servicio **backend** (el que apunta a `apps/audiomind/`)
2. Pestaña **Variables** → Edita estas dos:
   - `AUDIOMIND_R2_ACCESS_KEY_ID` = `<NUEVO_ACCESS_KEY>`
   - `AUDIOMIND_R2_SECRET_ACCESS_KEY` = `<NUEVO_SECRET_KEY>`
3. Click **Save** → Railway dispara **nuevo deployment** (build + start)
4. **Monitorea el deploy:**
   - Logs: debe mostrar `Session store: durable Supabase table sessions` (si Supabase OK)
   - Health check: `GET /health` → `{"status":"ok","service":"AudioMind"}`
   - Sube un archivo de prueba en Studio → verifica que el master se genera y descarga

> 💡 **Rollback instantáneo:** Si el nuevo deploy falla, en Railway → Deployments → click **Rollback** al anterior. Las credenciales viejas siguen funcionando hasta que las revoces.

---

## 4. Verificar en producción (post-deploy)

```bash
# Desde Studio (UI) o curl:
curl -X POST "https://waveia-production.up.railway.app/api/session/new" \
  -H "Content-Type: application/json" \
  -d '{"filename":"test.wav"}'

# Debe responder 200 con session_id. Luego sube un WAV real y masteriza un preset.
# Si el master se descarga → R2 funciona con claves nuevas.
```

---

## 5. Revocar claves ANTIGUAS (solo después de confirmar producción)

1. Cloudflare Dashboard → R2 → Manage R2 API tokens
2. Busca el token **antiguo** (el que estaba en Railway antes)
3. Click **...** → **Revoke** → Confirmar
4. Verifica que ya no aparece en la lista de tokens activos

> ✅ **Hecho.** Las claves expuestas ya no sirven. El backend usa las nuevas.

---

## Checklist rápido

- [ ] Nuevo token creado en Cloudflare (bucket-specific, Read&Write, TTL 90d)
- [ ] `scripts/verify_r2_keys.py` pasa con credenciales nuevas
- [ ] Railway backend actualizado con nuevas vars → deploy verde
- [ ] Studio sube + masteriza + descarga OK en producción
- [ ] Token antiguo revocado en Cloudflare
- [ ] Próxima rotación agendada (calendario +90 días)

---

## Notas de seguridad

| Qué NO hacer | Por qué |
|--------------|---------|
| Commitear claves en `.env` o código | Se filtran en git history |
| Usar mismo token para todo (frontend, backend, CI) | Una fuga compromete todo |
| Saltar validación local | Un typo en Railway = deploy roto + tiempo perdido |
| Revocar antes de validar deploy nuevo | Caída de servicio evitable |

---

## Script incluido

`scripts/verify_r2_keys.py` — valida endpoint, bucket, credenciales, subida/listado/borrado de 1 byte. Usa `boto3` (ya en deps del backend).