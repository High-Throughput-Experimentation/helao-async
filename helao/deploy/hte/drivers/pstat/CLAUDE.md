# hte pstat — BioLogic potentiostats, two backends

<!-- Split out of the root CLAUDE.md. Loaded when work touches this directory. -->

`helao/deploy/hte/servers/action/biologic_server.py` serves the same seven
technique endpoints from either of two drivers, chosen by the server's
`pstat_backend` param — `eclib` (default, `drivers/pstat/biologic/`, via
easy-biologic over TCP) or `olecom` (`drivers/pstat/biologic_ole/`, by
piloting the EC-Lab application over OLE COM). An absent key yields `eclib`,
so the four station configs that declare one (`hispec`, `odspechw`, `clad`,
`adss3`) keep working unedited; an *unrecognized* value raises,
because a typo must not hand an EC-Lab station the easy-biologic driver.
Both satisfy the `BiologicBackend` Protocol in `drivers/pstat/biologic_backend.py`.

The OLE path is not a variation on the EClib one. What is worth knowing before
editing it:

- **There is no programmatic technique construction.** `LoadSettings` takes an
  `.mps` file and nothing in the 32-function API builds a technique from
  arguments, so `.mps` templating is the transport for *every* endpoint, not
  an opt-in feature. `ModifyOnTheFly` exists but mutates a **running**
  experiment, by GUI caption, needing a second call for the unit.
- **The nine `.mps` templates cannot be produced from this repo.** They are
  authored in the EC-Lab GUI at a station. `templates/README.md` says which.
  A caption `technique.py` names but no template row matches raises
  `MpsParameterNotFound` at setup — deliberately, because the alternative is
  running the template's own default on a real cell with nothing to show it.
- **Data is polled out of the growing MPR file, one value per call.** `P_W` is
  derived as `|Ewe*I|`, which is EC-Lab's own definition of variable 70, and
  `cycle` comes from status index 10 — fetching either would cost a call per
  point to learn the same number. The manual's wording leaves open whether
  `MeasureDcValue` returns one point or all remaining ones; `MprCursor`
  advances by the length it receives, so a bulk return just makes it faster.
- **`Stop_rec1`/`Stop_rec2` (status index 0 == 4 or 5) mean "the last points
  are being recorded", not "stopped".** The driver finishes only at `Stop`,
  and then drains once more. Finishing at `Stop_rec` truncates the tail of
  every record, silently.
- **`ConnectDevice`/`ConnectDeviceByIP` auto-answer "Yes" to EC-Lab's
  firmware-upgrade prompt** and the API cannot suppress it, so a connect can
  flash a production instrument. The driver warns before calling; nothing more
  is possible from here.
- **A modal Windows message box blocks the COM call that raised it, forever.**
  `EnableMessagesWindows(0)` runs first at connect, and every call still goes
  through a thread executor under a timeout — which frees the caller and
  leaves the worker thread blocked, the same trade `OceanDirectExtrigExec`
  makes.
- **EC-Lab is a GUI a human can touch mid-run.** `SelectDevice`/`SelectChannel`
  mutate a global selection, so every call passes an explicit device and
  channel. The manual's own §6.1 example is internally inconsistent here (the
  prose says device 6, the code says `OLE_ConnectDevice(1)`).
- **TTL is not an API call.** Trigger In and Trigger Out are *techniques*
  (appendix 7.1 codes 38/39, 88/89), so a non-default `TTLwait`/`TTLsend`
  assembles a multi-technique `.mps` and renumbers both the `Technique : N`
  lines and the `Number of linked techniques` header, which EC-Lab reads
  positionally and does not repair.
- **Technique codes are duplicated across two families** — CA is 24 and 54,
  OCV 11 and 55, CV 6 and 57, PEIS 29 and 60, GEIS 30 and 61, CP 25 and 56.
  Which one a template yields depends on the template; status index 5 reports
  it back and the driver warns on a mismatch rather than refusing.
- **The `.mps` and `.mpr` ship with the action, moved at cleanup.** EC-Lab
  appends to the MPR for the whole run and `HelaoYml.misc_files` globs live
  directories, so writing straight into the action directory would upload a
  torn file.
- **The range enums are coerced in each backend's `setup()`, not in the
  endpoints.** Since 2026-09-07 the recorded action param is the string
  (`"AUTO"`, `"m1"`, `"BW4"`) rather than the vendor enum's integer.
- Only `biologic_ole/olecom_client.py` may import `comtypes`, and only inside
  a function; a test parses imports to enforce it. `python launch.py
  biologicole` is a hardware-free dev launch of the whole group, and
  `helao/hexagon/tests/test_biologic_column_contract.py` is the gate that both
  backends emit the same columns.
