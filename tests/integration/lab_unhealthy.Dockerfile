# CI-only intentional failure fixture: the new candidate must be stopped.
FROM busybox:1.36
HEALTHCHECK --interval=1s --timeout=1s --start-period=1s --retries=1 CMD ["false"]
USER 65534:65534
CMD ["sleep", "300"]
