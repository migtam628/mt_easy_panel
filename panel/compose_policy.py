"""Non-executing, restrictive Compose v0.1 compatibility analyzer.

This is deliberately a small safe subset for preview, NOT full Compose support.
No Docker CLI, network calls, interpolation, privileged execution or file writes.
"""
from __future__ import annotations

import re
import yaml

from panel.manifests import DIGEST

NAME = re.compile(r"^[a-z][a-z0-9_-]{1,47}$")


class ComposePolicyError(ValueError):
    pass


class NoAliasesLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            raise ComposePolicyError("YAML aliases are not accepted")
        return super().compose_node(parent,index)


def validate_compose(source: str) -> dict:
    if not 1 <= len(source) <= 32768:
        raise ComposePolicyError("Compose input must be 1-32768 characters")
    if "${" in source:
        raise ComposePolicyError("Environment interpolation is not supported in a safe preview")
    try:
        config = yaml.load(source, Loader=NoAliasesLoader)
    except yaml.YAMLError as exc:
        raise ComposePolicyError("Invalid Compose YAML") from exc
    if not isinstance(config, dict) or set(config) != {"services"}:
        raise ComposePolicyError("Only a top-level services mapping is supported")
    services = config["services"]
    if not isinstance(services, dict) or not 1 <= len(services) <= 4:
        raise ComposePolicyError("Specify 1-4 services")
    result = []
    for name, value in services.items():
        if not isinstance(name,str) or not NAME.fullmatch(name):
            raise ComposePolicyError("Invalid service name")
        if not isinstance(value,dict):
            raise ComposePolicyError(f"{name}: expected service mapping")
        options = set(value)
        if options != {"image","read_only","expose"}:
            raise ComposePolicyError(
                f"{name}: only image, read_only and expose are supported; disallowed/unknown options are rejected")
        image = value["image"]
        if not isinstance(image,str) or not DIGEST.fullmatch(image):
            raise ComposePolicyError(f"{name}: image must be pinned to a sha256 digest")
        if value["read_only"] is not True:
            raise ComposePolicyError(f"{name}: read_only must be true")
        expose = value["expose"]
        if not isinstance(expose,list) or not 1 <= len(expose) <= 3:
            raise ComposePolicyError(f"{name}: expose must list 1-3 internal ports")
        ports = []
        for port in expose:
            if isinstance(port,bool) or not isinstance(port,(int,str)) or not str(port).isdigit():
                raise ComposePolicyError(f"{name}: invalid internal port")
            p = int(port)
            if p < 1 or p > 65535 or p in ports:
                raise ComposePolicyError(f"{name}: invalid or duplicate internal port")
            ports.append(p)
        result.append({"service":name,"image":image,"internal_ports":ports,"read_only":True})
    return {
        "valid":True,"mode":"analysis-only","deployment_enabled":False,
        "service_count":len(result),"services":result,
        "warnings":["Only restricted Compose preview is supported; no container will be created."]
    }
