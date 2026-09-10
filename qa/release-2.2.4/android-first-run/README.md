# Preserved Android failure before preview lifecycle follow-up

Production verification run [34414086248](https://github.com/CyberBASSLord-666/LightForge/actions/runs/34414086248) used source `cf9a937583aa2ceeb105dddfbfb5c31a229910d2`. Its verification/build job passed. The Android job completed native Studio processing under screen-off/Doze and reopened the saved project, then failed with a focus-dispatch ANR while closing the Activity before Balanced inference.

These original failed records remain unchanged. The main-thread snapshots locate a hardware-renderer frame wait; launcher/SystemUI frame delays and an emulator warning about four vCPUs on a two-vCPU KVM host also occurred. That evidence does not isolate a single app or emulator cause.

The follow-up explicitly suspends preview render loops while paused, waits for an actual committed preview frame before lifecycle actions, disables all test animation scales and uses the supported two emulator cores. Full display resolution, graphics, native model passes and Android ANR limits are retained. A new successful Android run is required; these failed results are not promoted to passing evidence.
