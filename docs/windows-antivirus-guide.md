# Windows Antivirus Exclusions for Scubiee

Scubiee performs frequent file reads during indexing and change polling. Real-time
antivirus scanning (Windows Defender, etc.) can add 2-5s spikes per I/O operation,
causing slow status responses and timeouts.

## Recommended Exclusion Paths

| Path | Reason |
|------|--------|
| `%USERPROFILE%\.context-engine\` | Index store, embeddings, config |
| `%LOCALAPPDATA%\uv\tools\` | uv-installed scubiee + dependencies |
| `%TEMP%\fastembed_cache\` | ONNX model cache (large binary files) |
| `%USERPROFILE%\.cache\fastembed\` | Alternative FastEmbed cache location |
| `%USERPROFILE%\.cache\huggingface\` | HuggingFace model downloads |

## Add Exclusions via PowerShell (Run as Admin)

```powershell
# One-liner: add all recommended exclusions
@("$env:USERPROFILE\.context-engine", "$env:LOCALAPPDATA\uv\tools", "$env:TEMP\fastembed_cache", "$env:USERPROFILE\.cache\fastembed", "$env:USERPROFILE\.cache\huggingface") | ForEach-Object { Add-MpPreference -ExclusionPath $_ }
```

To verify current exclusions:

```powershell
Get-MpPreference | Select-Object -ExpandProperty ExclusionPath
```

## Add Exclusions via Windows Security UI

1. Open **Windows Security** > **Virus & threat protection**
2. Under **Virus & threat protection settings**, click **Manage settings**
3. Scroll to **Exclusions** > click **Add or remove exclusions**
4. Click **Add an exclusion** > **Folder** and add each path above

## Symptoms of AV Interference

- `scubiee status` shows random 2-5 second response time spikes
- `engine.log` contains file access errors (EBUSY, permission denied) on
  `.context-engine/` files that resolve on retry
- Index speed drops below 1 chunk/s intermittently (normal is 10+ chunk/s)
- The keeper/change-poll logs show `slow I/O detected` messages and backs off
  the poll interval automatically
- `scubiee setup` takes 5+ minutes (normally under 2 minutes)

## Third-Party Antivirus

For non-Defender AV (Norton, McAfee, Bitdefender, etc.), add the same paths
to your AV's real-time scanning exclusion list. Consult your AV documentation
for the equivalent setting.

## Verifying the Fix

After adding exclusions, restart the scubiee engine:

```powershell
scubiee engine stop
scubiee engine start
```

Then run `scubiee status` a few times — response time should be consistently
under 500ms without spikes.
