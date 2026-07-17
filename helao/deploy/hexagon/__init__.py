"""Launcher shim deployment for hexagon-composed servers (P1b1 DD-6).

Config entries opt in per server with `deployment: hexagon`; modules here
only delegate to helao.hexagon.app.factory — no server logic lives in this
package. Rollback = flip the key back to the legacy deployment."""
