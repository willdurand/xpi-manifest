# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
"""
Apply some defaults and minor modifications to the tasks defined in the github_release
kind.
"""

import os

from taskgraph.config import load_graph_config
from taskgraph.transforms.base import TransformSequence
from taskgraph.util.schema import resolve_keyed_by
from xpi_taskgraph.xpi_manifest import get_manifest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ROOT = os.path.join(BASE_DIR, "ci")

transforms = TransformSequence()


@transforms.add
def resolve_keys(config, tasks):
    for task in tasks:
        for key in ("worker.github-project", "worker.release-name"):
            resolve_keyed_by(
                task, key, item_name=task["name"], **{"level": config.params["level"]}
            )
        yield task


@transforms.add
def build_worker_definition(config, tasks):
    for task in tasks:
        if not (
            config.params.get("version")
            and config.params.get("xpi_name")
            and config.params.get("build_number")
        ):
            continue

        resolve_keyed_by(
            task, "scopes", item_name=task["name"], **{"level": config.params["level"]}
        )

        # translate input xpi_name to get manifest and graph info
        manifest = get_manifest()
        manifest_config = manifest[config.params["xpi_name"]]
        repo_prefix = manifest_config["repo-prefix"]
        graph_config = load_graph_config(ROOT)
        repo_url = graph_config["taskgraph"]["repositories"][repo_prefix][
            "default-repository"
        ]
        # repo_url: https://github.com/mozilla-releng/staging-xpi-public
        # repo_url: git@github.com:mozilla-extensions/https-upgrade-study-v2
        # repo: mozilla-releng/staging-xpi-public
        repo = repo_url.split("github.com")[-1]
        repo = repo.strip(":/")

        # if this is false in the manifest, no need to create github-release task
        if not manifest_config.get("enable-github-release", False):
            continue

        worker_definition = {
            "artifact-map": _build_artifact_map(task),
            "git-tag": config.params["head_tag"],
            "git-revision": config.params["xpi_revision"],
            "github-project": repo,
            "is-prerelease": False,
        }

        release_variables = {
            "xpi_name": config.params["xpi_name"],
            "version": config.params["version"],
            "build_number": config.params["build_number"],
        }
        tag_name = manifest_config.get(
            "release-tag", "{version}-build{build_number}"
        ).format(**release_variables)
        worker_definition["git-tag"] = tag_name
        release_name = manifest_config.get(
            "release-name", "{xpi_name}-{version}-build{build_number}"
        ).format(**release_variables)
        task["worker"]["release-name"] = release_name

        dep = task["primary-dependency"]
        worker_definition["upstream-artifacts"] = [
            {
                "taskId": {"task-reference": "<release-signing>"},
                "taskType": "signing",
                "paths": list(dep.attributes["xpis"].values()),
            }
        ]

        # TODO: test this once we can test on shipit
        if (
            "env" in dep.task.get("payload", {})
            and "ARTIFACT_PREFIX" in dep.task["payload"]["env"]
        ):
            if not dep.task["payload"]["env"]["ARTIFACT_PREFIX"].startswith("public"):
                scopes = task.setdefault("scopes", [])
                scopes.append(
                    "queue:get-artifact:{}/*".format(
                        dep.task["payload"]["env"]["ARTIFACT_PREFIX"].rstrip("/")
                    )
                )

        task["worker"].update(worker_definition)
        task["dependencies"] = {"release-signing": dep.label}
        del task["primary-dependency"]
        yield task


def _build_artifact_map(task):
    artifact_map = []
    dep = task["primary-dependency"]

    artifacts = {"paths": {}, "taskId": {"task-reference": "<release-signing>"}}
    for path in dep.attributes["xpis"].values():
        artifacts["paths"][path] = {"destinations": [path.split("/")[-1]]}
        artifact_map.append(artifacts)
    return artifact_map
