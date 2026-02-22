# Future Ideas

- **Burn rate estimate**: Calculate approximate usage rate from current utilization and time remaining until reset. E.g. "20% used with 2h left in a 5h window" gives a burn rate that can predict when you'll hit the limit.
- **Minimize to system tray**: Option to hide the overlay and restore it from a tray icon.
- **Resizable overlay**: Let the user scale the overlay up or down.
- **Themes**: Light mode, custom colors, transparency settings.
- **Encrypt stored tokens**: Use Windows `CryptProtectData`/`CryptUnprotectData` (DPAPI) to encrypt OAuth tokens in config.json instead of storing them in plaintext.
