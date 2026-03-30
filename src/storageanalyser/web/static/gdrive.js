/* Google Drive tab logic */
(function () {
    "use strict";

    var stepCreds = document.getElementById("gdrive-step-creds");
    var stepAuth = document.getElementById("gdrive-step-auth");
    var stepReady = document.getElementById("gdrive-step-ready");
    var alertBox = document.getElementById("gdrive-alert-box");
    var alertMsg = document.getElementById("gdrive-alert-msg");
    var progressEl = document.getElementById("gdrive-progress");
    var resultsEl = document.getElementById("gdrive-results");

    // ── Helpers ──────────────────────────────────────────────
    function humanSize(bytes) {
        if (bytes >= 1073741824) return (bytes / 1073741824).toFixed(1) + " GB";
        if (bytes >= 1048576) return (bytes / 1048576).toFixed(1) + " MB";
        if (bytes >= 1024) return (bytes / 1024).toFixed(1) + " KB";
        return bytes + " B";
    }

    function escapeHtml(s) {
        var d = document.createElement("div");
        d.textContent = s;
        return d.innerHTML;
    }

    function showAlert(msg) {
        alertMsg.textContent = msg;
        alertBox.classList.add("active");
    }

    function hideAlert() { alertBox.classList.remove("active"); }

    function showStep(step) {
        stepCreds.classList.add("hidden");
        stepAuth.classList.add("hidden");
        stepReady.classList.add("hidden");
        step.classList.remove("hidden");
    }

    // ── Check status on load ─────────────────────────────────
    function checkStatus() {
        fetch("/api/gdrive/status")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.authenticated) {
                    showStep(stepReady);
                    if (data.has_result) loadResult();
                } else if (data.configured) {
                    showStep(stepAuth);
                } else {
                    showStep(stepCreds);
                }
            });
    }
    checkStatus();

    // ── Upload credentials ───────────────────────────────────
    document.getElementById("gdrive-upload-btn").addEventListener("click", function () {
        var fileInput = document.getElementById("gdrive-creds-file");
        if (!fileInput.files.length) {
            showAlert("Select a credentials JSON file first");
            return;
        }
        hideAlert();
        var formData = new FormData();
        formData.append("file", fileInput.files[0]);

        fetch("/api/gdrive/credentials", { method: "POST", body: formData })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    showAlert(data.error);
                } else {
                    showStep(stepAuth);
                }
            })
            .catch(function (err) { showAlert("Upload failed: " + err.message); });
    });

    // ── Authorize ────────────────────────────────────────────
    document.getElementById("gdrive-auth-btn").addEventListener("click", function () {
        hideAlert();
        var btn = this;
        btn.disabled = true;
        btn.textContent = "Waiting for authorization...";

        fetch("/api/gdrive/auth", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                btn.disabled = false;
                btn.textContent = "Authorize Google Drive";
                if (data.error) {
                    showAlert(data.error);
                } else {
                    showStep(stepReady);
                }
            })
            .catch(function (err) {
                btn.disabled = false;
                btn.textContent = "Authorize Google Drive";
                showAlert("Auth failed: " + err.message);
            });
    });

    // ── Scan Drive ───────────────────────────────────────────
    function startScan() {
        hideAlert();
        progressEl.classList.add("active");
        resultsEl.classList.remove("active");

        var params = new URLSearchParams();
        if (document.getElementById("gdrive-dupes").checked) {
            params.set("find_duplicates", "true");
        }

        fetch("/api/gdrive/scan?" + params.toString(), { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    progressEl.classList.remove("active");
                    showAlert(data.error);
                    return;
                }
                pollResult();
            })
            .catch(function (err) {
                progressEl.classList.remove("active");
                showAlert("Scan failed: " + err.message);
            });
    }

    function pollResult() {
        fetch("/api/gdrive/result")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.status === "scanning") {
                    setTimeout(pollResult, 1500);
                    return;
                }
                progressEl.classList.remove("active");
                if (data.error) {
                    showAlert(data.error);
                    return;
                }
                renderResult(data);
            })
            .catch(function (err) {
                progressEl.classList.remove("active");
                showAlert("Failed to load results: " + err.message);
            });
    }

    document.getElementById("gdrive-scan-btn").addEventListener("click", startScan);
    document.getElementById("gdrive-rescan-btn").addEventListener("click", startScan);

    // ── Disconnect ───────────────────────────────────────────
    document.getElementById("gdrive-disconnect-btn").addEventListener("click", function () {
        fetch("/api/gdrive/disconnect", { method: "POST" })
            .then(function () {
                resultsEl.classList.remove("active");
                showStep(stepCreds);
            });
    });

    // ── Load existing result ─────────────────────────────────
    function loadResult() {
        fetch("/api/gdrive/result")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!data.error && data.quota) renderResult(data);
            });
    }

    // ── Render ───────────────────────────────────────────────
    function renderResult(data) {
        resultsEl.classList.add("active");

        var q = data.quota;
        document.getElementById("gdrive-email").textContent = q.email || "-";
        document.getElementById("gdrive-total-files").textContent = data.total_files.toLocaleString();
        document.getElementById("gdrive-usage").textContent = q.usage_in_drive_human;
        document.getElementById("gdrive-trash").textContent = q.usage_in_trash_human;
        document.getElementById("gdrive-free").textContent = q.free_human;
        document.getElementById("gdrive-quota").textContent = q.limit_human;

        // Pie chart
        if (q.limit > 0) {
            renderPie(q);
        }

        // Type breakdown bars
        renderTypeBars(data.type_breakdown, data.total_size);

        // File table
        renderFiles(data.files);

        // Duplicates
        var dupesSection = document.getElementById("gdrive-dupes-section");
        if (data.duplicates && data.duplicates.length > 0) {
            dupesSection.classList.remove("hidden");
            document.getElementById("gdrive-dupes-savings").textContent =
                "Potential savings: " + data.duplicate_savings_human;
            renderDuplicates(data.duplicates);
        } else {
            dupesSection.classList.add("hidden");
        }
    }

    function renderPie(q) {
        var total = q.limit;
        var trash = q.usage_in_trash;
        var driveUsed = Math.max(0, q.usage_in_drive - trash);
        var free = q.free;

        var slices = [
            { label: "Drive", value: driveUsed, color: "#6c8cff", human: humanSize(driveUsed) },
            { label: "Trash", value: trash, color: "#ff6b6b", human: humanSize(trash) },
            { label: "Free", value: free, color: "#51cf66", human: humanSize(free) },
        ];

        var svg = document.getElementById("gdrive-pie");
        svg.innerHTML = "";
        var cx = 100, cy = 100, r = 90;
        var startAngle = -Math.PI / 2;

        slices.forEach(function (s) {
            if (s.value <= 0) return;
            var fraction = s.value / total;
            var endAngle = startAngle + fraction * 2 * Math.PI;
            var largeArc = fraction > 0.5 ? 1 : 0;

            var x1 = cx + r * Math.cos(startAngle);
            var y1 = cy + r * Math.sin(startAngle);
            var x2 = cx + r * Math.cos(endAngle);
            var y2 = cy + r * Math.sin(endAngle);

            var path;
            if (fraction >= 0.9999) {
                path = "M " + (cx - r) + " " + cy +
                       " A " + r + " " + r + " 0 1 1 " + (cx + r) + " " + cy +
                       " A " + r + " " + r + " 0 1 1 " + (cx - r) + " " + cy + " Z";
            } else {
                path = "M " + cx + " " + cy +
                       " L " + x1 + " " + y1 +
                       " A " + r + " " + r + " 0 " + largeArc + " 1 " + x2 + " " + y2 +
                       " Z";
            }

            var el = document.createElementNS("http://www.w3.org/2000/svg", "path");
            el.setAttribute("d", path);
            el.setAttribute("fill", s.color);
            el.setAttribute("stroke", "rgba(0,0,0,0.3)");
            el.setAttribute("stroke-width", "1");
            svg.appendChild(el);
            startAngle = endAngle;
        });

        // Center hole
        var hole = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        hole.setAttribute("cx", cx);
        hole.setAttribute("cy", cy);
        hole.setAttribute("r", "45");
        hole.setAttribute("fill", "#0f1117");
        svg.appendChild(hole);

        // Legend
        var legend = document.getElementById("gdrive-pie-legend");
        legend.innerHTML = "";
        slices.forEach(function (s) {
            if (s.value <= 0) return;
            var item = document.createElement("div");
            item.className = "legend-item";
            item.innerHTML =
                '<span class="legend-swatch" style="background:' + s.color + '"></span>' +
                '<span class="legend-label">' + escapeHtml(s.label) + '</span> ' +
                '<span class="legend-value">' + escapeHtml(s.human) + '</span>';
            legend.appendChild(item);
        });
    }

    function renderTypeBars(breakdown, totalSize) {
        var container = document.getElementById("gdrive-type-bars");
        container.innerHTML = "";
        if (!totalSize) return;

        var TYPE_COLORS = [
            "#6c8cff", "#ff6b6b", "#ffa94d", "#51cf66", "#b197fc",
            "#ffd43b", "#38d9a9", "#ff8787", "#74c0fc", "#e599f7",
        ];

        var types = Object.keys(breakdown);
        types.forEach(function (type, i) {
            var size = breakdown[type];
            var pct = Math.max(1, (size / totalSize) * 100);

            var row = document.createElement("div");
            row.className = "cat-bar-row";

            var label = document.createElement("div");
            label.className = "cat-bar-label";
            label.textContent = type;

            var track = document.createElement("div");
            track.className = "cat-bar-track";

            var fill = document.createElement("div");
            fill.className = "cat-bar-fill";
            fill.style.width = pct + "%";
            fill.style.background = TYPE_COLORS[i % TYPE_COLORS.length];
            track.appendChild(fill);

            var sizeEl = document.createElement("div");
            sizeEl.className = "cat-bar-size";
            sizeEl.textContent = humanSize(size);

            row.appendChild(label);
            row.appendChild(track);
            row.appendChild(sizeEl);
            container.appendChild(row);
        });
    }

    function renderFiles(files) {
        var tbody = document.getElementById("gdrive-files-tbody");
        tbody.innerHTML = "";

        files.forEach(function (f) {
            if (f.size === 0) return;
            var tr = document.createElement("tr");

            var nameCell = document.createElement("td");
            nameCell.textContent = f.name;
            nameCell.title = f.name;
            nameCell.style.maxWidth = "400px";
            nameCell.style.wordBreak = "break-all";

            var sizeCell = document.createElement("td");
            sizeCell.className = "col-size";
            sizeCell.textContent = f.size_human;

            var typeCell = document.createElement("td");
            typeCell.textContent = simplifyMime(f.mime_type);
            typeCell.style.fontSize = "0.75rem";
            typeCell.style.color = "var(--text-muted)";

            var dateCell = document.createElement("td");
            dateCell.style.whiteSpace = "nowrap";
            dateCell.style.fontSize = "0.8rem";
            if (f.modified_time) {
                dateCell.textContent = f.modified_time.substring(0, 10);
            }

            var linkCell = document.createElement("td");
            if (f.web_view_link) {
                var a = document.createElement("a");
                a.href = f.web_view_link;
                a.target = "_blank";
                a.textContent = "Open";
                a.style.color = "var(--accent)";
                a.style.textDecoration = "none";
                a.style.fontSize = "0.8rem";
                linkCell.appendChild(a);
            }

            tr.appendChild(nameCell);
            tr.appendChild(sizeCell);
            tr.appendChild(typeCell);
            tr.appendChild(dateCell);
            tr.appendChild(linkCell);
            tbody.appendChild(tr);
        });
    }

    function renderDuplicates(groups) {
        var container = document.getElementById("gdrive-dupes-groups");
        container.innerHTML = "";

        groups.forEach(function (group) {
            var card = document.createElement("div");
            card.className = "dedup-group";

            var header = document.createElement("div");
            header.className = "dedup-group-header";

            var title = document.createElement("span");
            title.className = "dedup-group-title";
            title.textContent = group.count + " copies";

            var badge = document.createElement("span");
            badge.className = "dedup-group-size";
            badge.textContent = group.size_human + " each \u2014 save " + group.savings_human;

            header.appendChild(title);
            header.appendChild(badge);
            card.appendChild(header);

            var list = document.createElement("div");
            list.style.marginTop = "8px";
            group.files.forEach(function (f) {
                var row = document.createElement("div");
                row.style.display = "flex";
                row.style.gap = "12px";
                row.style.alignItems = "center";
                row.style.padding = "4px 0";
                row.style.borderBottom = "1px solid var(--border)";
                row.style.fontSize = "0.8rem";

                var nameEl = document.createElement("span");
                nameEl.textContent = f.name;
                nameEl.style.flex = "1";
                nameEl.style.wordBreak = "break-all";
                row.appendChild(nameEl);

                var sizeEl = document.createElement("span");
                sizeEl.textContent = f.size_human;
                sizeEl.style.color = "var(--text-muted)";
                row.appendChild(sizeEl);

                if (f.web_view_link) {
                    var a = document.createElement("a");
                    a.href = f.web_view_link;
                    a.target = "_blank";
                    a.textContent = "Open";
                    a.style.color = "var(--accent)";
                    a.style.textDecoration = "none";
                    row.appendChild(a);
                }

                list.appendChild(row);
            });
            card.appendChild(list);
            container.appendChild(card);
        });
    }

    function simplifyMime(mime) {
        if (!mime) return "";
        var LABELS = {
            "application/vnd.google-apps.document": "Google Doc",
            "application/vnd.google-apps.spreadsheet": "Google Sheet",
            "application/vnd.google-apps.presentation": "Google Slides",
            "application/vnd.google-apps.form": "Google Form",
            "application/vnd.google-apps.folder": "Folder",
            "application/pdf": "PDF",
            "application/zip": "ZIP",
        };
        if (LABELS[mime]) return LABELS[mime];
        if (mime.startsWith("image/")) return mime.split("/")[1].toUpperCase();
        if (mime.startsWith("video/")) return "Video";
        if (mime.startsWith("audio/")) return "Audio";
        if (mime.startsWith("text/")) return "Text";
        return mime.split("/").pop();
    }
})();
