# Publicación en TikTok: opciones oficiales

> Investigación de septiembre de 2026 a partir de la documentación pública de TikTok for Developers. **Vuelve a comprobarla antes de implementar**, porque los requisitos cambian:
> - https://developers.tiktok.com/doc/content-posting-api-get-started
> - https://developers.tiktok.com/docs/en/content-posting-api-reference-direct-post
> - https://developers.tiktok.com/docs/en/content-sharing-guidelines

## Opciones oficiales (Content Posting API)

| Modo | Permiso (scope) | Qué hace |
|---|---|---|
| Subida a borradores (*upload*) | `video.upload` | El video llega a la bandeja o borradores del creador, que lo termina y publica desde la app. **Es el modo recomendado para empezar**, porque mantiene la revisión humana. |
| Publicación directa (*Direct Post*) | `video.publish` | Publica directamente en el perfil. |

## Requisitos y restricciones

- Registrar una app en TikTok for Developers, añadir el producto Content Posting API y obtener `client_key` / `client_secret`.
- Autorización OAuth del propietario de la cuenta (Login Kit) para obtener el token de acceso.
- **Clientes no auditados:** todo lo que publican queda en visibilidad privada (`SELF_ONLY`), sea cual sea la privacidad solicitada, y solo pueden publicar hasta 5 usuarios en 24 horas.
- Para publicar en público hay que superar la **auditoría** de TikTok, que verifica el cumplimiento de sus términos y directrices de UX (por ejemplo, mostrar la vista previa, permitir elegir la privacidad y obtener el consentimiento explícito del usuario).

## Plan para este proyecto

1. **Ahora (fase 1):** el sistema solo crea `output/<idioma>/<fecha>/` y `output/READY_TO_PUBLISH.md` con la descripción y los hashtags. Tú subes el video a mano.
2. **Fase 4:** implementar `upload to inbox` (`video.upload`) en `src/publishing.py`, solo para videos con `qc_report.approved == true`, y con confirmación manual.
3. Direct Post solo después de la auditoría y si lo apruebas expresamente.

No se usarán bots de navegador ni automatizaciones que eviten las medidas de seguridad de la plataforma.
