# CI-only fixture. This image never receives host ports, volumes or a network.
FROM busybox:1.36
HEALTHCHECK --interval=1s --timeout=1s --start-period=1s --retries=2 CMD ["true"]
USER 65534:65534
CMD ["sleep", "300"]
