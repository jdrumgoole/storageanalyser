/* StorageAnalyser Web UI */
(function () {
    "use strict";

    const CATEGORY_LABELS = {
        junk_directory: "Cache/Junk",
        build_artifact: "Build Artifact",
        large_file: "Large File",
        stale_file: "Stale File",
        duplicate: "Duplicate",
        old_download: "Old Download",
    };

    const CATEGORY_COLORS = {
        junk_directory: "#ff6b6b",
        build_artifact: "#ffa94d",
        large_file: "#6c8cff",
        stale_file: "#b197fc",
        duplicate: "#38d9a9",
        old_download: "#ffd43b",
    };

    // ── Tab switching ─────────────────────────────────────────
    document.querySelectorAll(".tab").forEach(function (tab) {
        tab.addEventListener("click", function () {
            document.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
            document.querySelectorAll(".tab-content").forEach(function (c) { c.classList.remove("active"); });
            tab.classList.add("active");
            document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
        });
    });

    // ── DOM refs ─────────────────────────────────────────────
    const scanForm = document.getElementById("scan-form");
    const scanBtn = document.getElementById("scan-btn");
    const progressSection = document.getElementById("progress-section");
    const progressPhase = document.getElementById("progress-phase");
    const progressStatus = document.getElementById("progress-status");
    const alertBox = document.getElementById("alert-box");
    const alertMsg = document.getElementById("alert-msg");
    const resultsSection = document.getElementById("results-section");

    // ── Remembered Ignore Dirs ────────────────────────────────
    var inputPath = document.getElementById("input-path");
    var inputIgnore = document.getElementById("input-ignore");

    function loadIgnoreDirs() {
        var path = inputPath.value.trim();
        if (!path) return;
        fetch("/api/scan/ignore-dirs?path=" + encodeURIComponent(path))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.ignore_dirs && data.ignore_dirs.length > 0 && !inputIgnore.value.trim()) {
                    inputIgnore.value = data.ignore_dirs.join(", ");
                }
            })
            .catch(function () {});
    }

    // Load on startup and when the path field loses focus
    loadIgnoreDirs();
    inputPath.addEventListener("change", function () {
        inputIgnore.value = "";
        loadIgnoreDirs();
    });

    // ── Skipped Directories ────────────────────────────────────
    var skippedDirsList = document.getElementById("skipped-dirs-list");

    function loadSkippedDirs() {
        fetch("/api/scan/skipped-dirs")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                skippedDirsList.innerHTML = "";
                data.dirs.forEach(function (d) {
                    var label = document.createElement("label");
                    label.className = "skipped-dir-chip";
                    label.title = d.reason;

                    var cb = document.createElement("input");
                    cb.type = "checkbox";
                    cb.dataset.dirName = d.name;
                    cb.addEventListener("change", function () {
                        label.classList.toggle("included", cb.checked);
                    });

                    var nameSpan = document.createElement("span");
                    nameSpan.textContent = d.name;

                    var reasonSpan = document.createElement("span");
                    reasonSpan.className = "chip-reason";
                    reasonSpan.textContent = d.reason;

                    label.appendChild(cb);
                    label.appendChild(nameSpan);
                    label.appendChild(reasonSpan);
                    skippedDirsList.appendChild(label);
                });
            })
            .catch(function () {});
    }

    loadSkippedDirs();

    function getIncludeDirs() {
        var dirs = [];
        skippedDirsList.querySelectorAll("input:checked").forEach(function (cb) {
            dirs.push(cb.dataset.dirName);
        });
        return dirs;
    }

    // ── Scan Controller ──────────────────────────────────────
    let eventSource = null;

    var scanning = false;

    scanForm.addEventListener("submit", function (e) {
        e.preventDefault();
        if (scanning) {
            stopScan();
        } else {
            startScan();
        }
    });

    function stopScan() {
        scanBtn.disabled = true;
        scanBtn.textContent = "Stopping\u2026";
        fetch("/api/scan/cancel", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function () {
                // The SSE handler will pick up the done/error event
                // and call resetScanBtn via loadResults
            })
            .catch(function () {
                resetScanBtn();
            });
    }

    function startScan() {
        var params = new URLSearchParams();
        params.set("path", document.getElementById("input-path").value);
        params.set("top_n", document.getElementById("input-topn").value);
        params.set("threshold_mb", document.getElementById("input-threshold").value);
        params.set("workers", document.getElementById("input-workers").value);
        if (document.getElementById("input-duplicates").checked) {
            params.set("find_duplicates", "true");
        }
        var ignoreRaw = document.getElementById("input-ignore").value.trim();
        if (ignoreRaw) {
            ignoreRaw.split(",").forEach(function (d) {
                var trimmed = d.trim();
                if (trimmed) params.append("ignore_dirs", trimmed);
            });
        }
        getIncludeDirs().forEach(function (d) {
            params.append("include_dirs", d);
        });

        hideAlert();
        scanning = true;
        scanBtn.disabled = false;
        scanBtn.textContent = "Stop Scan";
        scanBtn.classList.remove("btn-primary");
        scanBtn.classList.add("btn-danger");
        progressSection.classList.add("active");
        resultsSection.classList.remove("active");
        progressPhase.textContent = "Scanning...";
        progressStatus.textContent = "";
        progressBarFill.classList.remove("determinate");
        progressBarFill.style.width = "";
        progressPct.textContent = "";
        progressPct.classList.add("hidden");

        fetch("/api/scan?" + params.toString(), { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    showAlert(data.error);
                    resetScanBtn();
                    return;
                }
                openSSE();
            })
            .catch(function (err) {
                showAlert("Failed to start scan: " + err.message);
                resetScanBtn();
            });
    }

    var progressBarFill = document.querySelector(".progress-bar-fill");
    var progressPct = document.getElementById("progress-pct");

    function openSSE() {
        eventSource = new EventSource("/api/scan/events");
        eventSource.onmessage = function (e) {
            var data = JSON.parse(e.data);
            if (data.type === "progress") {
                progressPhase.textContent = data.message;
                if (data.phase === "duplicates") {
                    // Duplicate hashing phase: files_scanned = hashed count,
                    // bytes_scanned = total to hash
                    updateProgressBar(data.files_scanned, data.bytes_scanned);
                    progressStatus.textContent =
                        "Hashed " + data.files_scanned.toLocaleString() +
                        " of " + data.bytes_scanned.toLocaleString() + " candidates";
                } else {
                    updateProgressBar(data.files_scanned, data.expected_files);
                    if (data.files_scanned > 0) {
                        progressStatus.textContent =
                            data.files_scanned.toLocaleString() + " files \u00b7 " +
                            humanSize(data.bytes_scanned);
                    }
                }
            } else if (data.type === "done") {
                eventSource.close();
                eventSource = null;
                loadResults();
            } else if (data.type === "error") {
                eventSource.close();
                eventSource = null;
                showAlert("Scan error: " + data.message);
                resetScanBtn();
            }
        };
        eventSource.onerror = function () {
            if (eventSource) {
                eventSource.close();
                eventSource = null;
            }
            /* The scan might have finished between events; check status */
            fetch("/api/scan/status")
                .then(function (r) { return r.json(); })
                .then(function (status) {
                    if (status.has_result) {
                        loadResults();
                    } else if (!status.active) {
                        showAlert("Connection to scan lost");
                        resetScanBtn();
                    }
                });
        };
    }

    window.addEventListener("beforeunload", function () {
        if (eventSource) eventSource.close();
    });

    function updateProgressBar(filesScanned, expectedFiles) {
        if (expectedFiles && expectedFiles > 0 && filesScanned > 0) {
            // Determinate mode — show real percentage
            var pct = Math.min(100, Math.round((filesScanned / expectedFiles) * 100));
            progressBarFill.classList.add("determinate");
            progressBarFill.style.width = pct + "%";
            progressPct.textContent = pct + "%";
            progressPct.classList.remove("hidden");
        }
        // Otherwise keep the indeterminate sliding animation (CSS default)
    }

    function showAlert(msg) {
        alertMsg.textContent = msg;
        alertBox.classList.add("active");
        progressSection.classList.remove("active");
    }

    function hideAlert() {
        alertBox.classList.remove("active");
    }

    function resetScanBtn() {
        scanning = false;
        scanBtn.disabled = false;
        scanBtn.textContent = "Start Scan";
        scanBtn.classList.remove("btn-danger");
        scanBtn.classList.add("btn-primary");
        progressSection.classList.remove("active");
    }

    // ── Load Results ─────────────────────────────────────────
    function loadResults() {
        fetch("/api/scan/result")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    showAlert(data.error);
                    resetScanBtn();
                    return;
                }
                scanning = false;
                progressSection.classList.remove("active");
                resultsSection.classList.add("active");
                scanBtn.disabled = false;
                scanBtn.textContent = "New Scan";
                scanBtn.classList.remove("btn-danger");
                scanBtn.classList.add("btn-primary");
                renderSummary(data);
                renderCategoryChart(data.category_breakdown, data.reclaimable);
                renderTreemap(data.recommendations);
                renderTable(data.recommendations);
            })
            .catch(function (err) {
                showAlert("Failed to load results: " + err.message);
                resetScanBtn();
            });
    }

    // ── Summary Cards + Pie Chart ──────────────────────────────
    function renderSummary(data) {
        document.getElementById("stat-files").textContent = data.total_scanned.toLocaleString();
        document.getElementById("stat-size").textContent = data.total_size_human;
        document.getElementById("stat-reclaimable").textContent = data.reclaimable_human;
        document.getElementById("stat-time").textContent = data.scan_seconds + "s";
        document.getElementById("stat-free").textContent = data.disk_free_human || "-";
        document.getElementById("stat-disk-total").textContent = data.disk_total_human || "-";

        if (data.disk_total > 0) {
            renderDiskPie(data);
        }
    }

    function renderDiskPie(data) {
        var total = data.disk_total;
        var free = data.disk_free;
        var reclaimable = data.reclaimable;
        var usedOther = Math.max(0, total - free - reclaimable);

        var slices = [
            { label: "Used", value: usedOther, color: "#5c5f73", human: humanSize(usedOther) },
            { label: "Reclaimable", value: reclaimable, color: "#ff6b6b", human: humanSize(reclaimable) },
            { label: "Free", value: free, color: "#51cf66", human: humanSize(free) },
        ];

        var svg = document.getElementById("disk-pie");
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
                // Full circle — arc commands can't draw a complete circle
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

        // Legend
        var legend = document.getElementById("disk-pie-legend");
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

    // ── Category Chart ───────────────────────────────────────
    function renderCategoryChart(breakdown, totalReclaimable) {
        var container = document.getElementById("category-bars");
        container.innerHTML = "";
        if (!totalReclaimable) return;

        var cats = Object.keys(breakdown).sort(function (a, b) {
            return breakdown[b] - breakdown[a];
        });

        cats.forEach(function (cat) {
            var size = breakdown[cat];
            var pct = Math.max(1, (size / totalReclaimable) * 100);

            var row = document.createElement("div");
            row.className = "cat-bar-row";

            var label = document.createElement("div");
            label.className = "cat-bar-label";
            label.textContent = CATEGORY_LABELS[cat] || cat;

            var track = document.createElement("div");
            track.className = "cat-bar-track";

            var fill = document.createElement("div");
            fill.className = "cat-bar-fill";
            fill.style.width = pct + "%";
            fill.style.background = CATEGORY_COLORS[cat] || "#888";
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

    // ── Treemap ──────────────────────────────────────────────
    function renderTreemap(recommendations) {
        var container = document.getElementById("treemap-container");
        container.innerHTML = "";
        if (!recommendations || recommendations.length === 0) return;

        var tooltip = document.getElementById("treemap-tooltip");
        var rect = container.getBoundingClientRect();
        var W = rect.width;
        var H = rect.height;

        // Group by category, then flatten children sorted by size
        var groups = {};
        recommendations.forEach(function (r) {
            if (!groups[r.category]) groups[r.category] = { size: 0, items: [] };
            groups[r.category].size += r.size;
            groups[r.category].items.push(r);
        });

        var nodes = Object.keys(groups).map(function (cat) {
            return { category: cat, size: groups[cat].size, items: groups[cat].items };
        }).sort(function (a, b) { return b.size - a.size; });

        // Squarified treemap layout
        var rects = squarify(nodes.map(function (n) { return n.size; }), 0, 0, W, H);

        rects.forEach(function (r, i) {
            var node = nodes[i];
            // Sub-layout within this category rect
            var subRects = squarify(
                node.items.map(function (it) { return it.size; }),
                r.x, r.y, r.w, r.h
            );

            subRects.forEach(function (sr, j) {
                var item = node.items[j];
                var cell = document.createElement("div");
                cell.className = "treemap-cell";
                cell.style.left = sr.x + "px";
                cell.style.top = sr.y + "px";
                cell.style.width = Math.max(0, sr.w - 2) + "px";
                cell.style.height = Math.max(0, sr.h - 2) + "px";
                cell.style.background = CATEGORY_COLORS[node.category] || "#888";

                if (sr.w > 50 && sr.h > 20) {
                    var lbl = document.createElement("span");
                    lbl.className = "treemap-cell-label";
                    lbl.textContent = shortPath(item.path);
                    cell.appendChild(lbl);
                }

                cell.addEventListener("mouseenter", function (e) {
                    tooltip.querySelector(".tt-path").textContent = item.path;
                    tooltip.querySelector(".tt-size").textContent = item.size_human;
                    tooltip.querySelector(".tt-reason").textContent = item.reason;
                    tooltip.classList.add("active");
                });
                cell.addEventListener("mousemove", function (e) {
                    tooltip.style.left = (e.clientX + 12) + "px";
                    tooltip.style.top = (e.clientY + 12) + "px";
                });
                cell.addEventListener("mouseleave", function () {
                    tooltip.classList.remove("active");
                });
                cell.addEventListener("click", function () {
                    tooltip.classList.remove("active");
                    scrollToRecommendation(item.path, node.category);
                });

                container.appendChild(cell);
            });
        });
    }

    /**
     * Squarified treemap layout.
     * Takes an array of sizes and a bounding rect, returns [{x, y, w, h}].
     */
    function squarify(sizes, x, y, w, h) {
        var total = sizes.reduce(function (a, b) { return a + b; }, 0);
        if (total === 0 || sizes.length === 0) return [];

        var result = [];
        var remaining = sizes.slice();
        var rx = x, ry = y, rw = w, rh = h;

        while (remaining.length > 0) {
            var rTotal = remaining.reduce(function (a, b) { return a + b; }, 0);
            var shortSide = Math.min(rw, rh);
            var row = [remaining[0]];
            remaining = remaining.slice(1);

            var rowRatio = worstRatio(row, shortSide, rTotal, rw * rh);
            while (remaining.length > 0) {
                var candidate = row.concat([remaining[0]]);
                var newRatio = worstRatio(candidate, shortSide, rTotal, rw * rh);
                if (newRatio <= rowRatio) {
                    row = candidate;
                    remaining = remaining.slice(1);
                    rowRatio = newRatio;
                } else {
                    break;
                }
            }

            // Layout this row
            var rowSum = row.reduce(function (a, b) { return a + b; }, 0);
            var rowArea = (rowSum / rTotal) * rw * rh;

            if (rw >= rh) {
                var rowWidth = rowArea / rh;
                if (rowWidth < 0.5) rowWidth = 0.5;
                var cy = ry;
                row.forEach(function (s) {
                    var cellH = (s / rowSum) * rh;
                    result.push({ x: rx, y: cy, w: rowWidth, h: cellH });
                    cy += cellH;
                });
                rx += rowWidth;
                rw -= rowWidth;
            } else {
                var rowHeight = rowArea / rw;
                if (rowHeight < 0.5) rowHeight = 0.5;
                var cx = rx;
                row.forEach(function (s) {
                    var cellW = (s / rowSum) * rw;
                    result.push({ x: cx, y: ry, w: cellW, h: rowHeight });
                    cx += cellW;
                });
                ry += rowHeight;
                rh -= rowHeight;
            }
        }
        return result;
    }

    function worstRatio(row, shortSide, totalSize, totalArea) {
        var rowSum = row.reduce(function (a, b) { return a + b; }, 0);
        var rowArea = (rowSum / totalSize) * totalArea;
        var side = rowArea / shortSide;
        if (side === 0) return Infinity;
        var worst = 0;
        row.forEach(function (s) {
            var cellArea = (s / totalSize) * totalArea;
            var cellSide = cellArea / side;
            if (cellSide === 0) return;
            var ratio = Math.max(side / cellSide, cellSide / side);
            if (ratio > worst) worst = ratio;
        });
        return worst;
    }

    function shortPath(p) {
        // Normalise to forward slashes for display
        var np = p.replace(/\\/g, "/");
        // macOS/Linux: /Users/name/... or /home/name/...
        var home = np.indexOf("/Users/");
        if (home < 0) home = np.indexOf("/home/");
        if (home >= 0) {
            var parts = np.substring(home).split("/");
            if (parts.length > 3) {
                return "~/" + parts.slice(3).join("/");
            }
        }
        // Windows: C:/Users/name/...
        var winMatch = np.match(/^[A-Za-z]:\/Users\/[^/]+\/(.+)/);
        if (winMatch) {
            return "~/" + winMatch[1];
        }
        var parts2 = np.split("/");
        return parts2[parts2.length - 1] || p;
    }

    /**
     * Elide middle directories: ~/first_dir/.../filename
     * Keeps the first directory after ~/ and the filename.
     */
    function elidePath(p) {
        var s = shortPath(p);  // normalise to ~/...
        var parts = s.split("/");
        // Need at least ~/dir/subdir/file to elide (4 parts: ~, dir, ..., file)
        if (parts.length <= 3) return s;
        return parts[0] + "/" + parts[1] + "/.../" + parts[parts.length - 1];
    }

    /**
     * Replace full paths in a reason string with elided versions.
     */
    function elideReason(reason) {
        // Match absolute paths: /unix/path or C:\windows\path
        return reason.replace(/(?:\/\S+|[A-Za-z]:[\\\/]\S+)/g, function (match) {
            // Remove trailing punctuation that isn't part of the path
            var trail = "";
            var m = match.match(/[,)]+$/);
            if (m) {
                trail = m[0];
                match = match.substring(0, match.length - trail.length);
            }
            return elidePath(match) + trail;
        });
    }

    /** Return the display path based on the elide toggle state. */
    function displayPath(p) {
        return elidePathsEnabled ? elidePath(p) : shortPath(p);
    }

    /** Return the display reason based on the elide toggle state. */
    function displayReason(reason) {
        return elidePathsEnabled ? elideReason(reason) : reason;
    }

    var elidePathsEnabled = true;

    // ── Recommendations Table with Category Tabs ──────────────
    var currentRecs = [];
    var tabSortState = {};  // per-tab sort state: { category: { col, dir } }

    function renderTable(recommendations) {
        currentRecs = recommendations;

        // Group by category, sorted by total size descending
        var groups = {};
        var groupSizes = {};
        recommendations.forEach(function (r) {
            if (!groups[r.category]) {
                groups[r.category] = [];
                groupSizes[r.category] = 0;
            }
            groups[r.category].push(r);
            groupSizes[r.category] += r.size;
        });

        var categoryOrder = Object.keys(groups).sort(function (a, b) {
            return groupSizes[b] - groupSizes[a];
        });

        // Add "All" tab first
        categoryOrder.unshift("all");

        // Build tabs
        var tabsContainer = document.getElementById("recs-tabs");
        tabsContainer.innerHTML = "";
        var contentsContainer = document.getElementById("recs-tab-contents");
        contentsContainer.innerHTML = "";

        categoryOrder.forEach(function (cat, idx) {
            var isAll = cat === "all";
            var items = isAll ? recommendations : groups[cat];
            var label = isAll ? "All" : (CATEGORY_LABELS[cat] || cat);
            var count = items.length;

            // Tab button
            var tabBtn = document.createElement("button");
            tabBtn.className = "recs-tab" + (idx === 0 ? " active" : "");
            tabBtn.dataset.recsTab = cat;
            tabBtn.innerHTML = escapeHtml(label) +
                ' <span class="recs-tab-count">' + count + '</span>';
            tabBtn.addEventListener("click", function () {
                tabsContainer.querySelectorAll(".recs-tab").forEach(function (t) {
                    t.classList.remove("active");
                });
                contentsContainer.querySelectorAll(".recs-tab-panel").forEach(function (p) {
                    p.classList.remove("active");
                });
                tabBtn.classList.add("active");
                document.getElementById("recs-panel-" + cat).classList.add("active");
            });
            tabsContainer.appendChild(tabBtn);

            // Tab panel with table
            var panel = document.createElement("div");
            panel.className = "recs-tab-panel" + (idx === 0 ? " active" : "");
            panel.id = "recs-panel-" + cat;

            // Summary line showing total size for this category
            if (!isAll) {
                var summary = document.createElement("div");
                summary.className = "recs-tab-summary";
                summary.innerHTML = '<strong>' + escapeHtml(label) + '</strong>: ' +
                    count + (count === 1 ? ' item' : ' items') +
                    ', <strong>' + escapeHtml(humanSize(groupSizes[cat])) + '</strong> total';
                panel.appendChild(summary);
            }

            var table = document.createElement("table");
            table.className = "recs-table";

            var thead = document.createElement("thead");
            var headerRow = document.createElement("tr");

            // Select-all checkbox for this tab
            var thCheck = document.createElement("th");
            thCheck.className = "col-check";
            var selectAllCb = document.createElement("input");
            selectAllCb.type = "checkbox";
            selectAllCb.className = "select-all-tab";
            selectAllCb.dataset.recsTab = cat;
            thCheck.appendChild(selectAllCb);
            headerRow.appendChild(thCheck);

            // Column headers (skip Category for individual category tabs)
            var columns = isAll
                ? [
                    { col: "category", label: "Category", cls: "col-category" },
                    { col: "path", label: "Path", cls: "" },
                    { col: "size", label: "Size", cls: "col-size" },
                    { col: "age_days", label: "Age", cls: "col-age" },
                    { col: "priority_score", label: "Priority", cls: "col-score" },
                    { col: "reason", label: "Reason", cls: "col-reason" },
                  ]
                : [
                    { col: "path", label: "Path", cls: "" },
                    { col: "size", label: "Size", cls: "col-size" },
                    { col: "age_days", label: "Age", cls: "col-age" },
                    { col: "priority_score", label: "Priority", cls: "col-score" },
                    { col: "reason", label: "Reason", cls: "col-reason" },
                  ];

            columns.forEach(function (c) {
                var th = document.createElement("th");
                th.dataset.col = c.col;
                th.dataset.recsTab = cat;
                if (c.cls) th.className = c.cls;
                th.textContent = c.label;
                headerRow.appendChild(th);
            });

            thead.appendChild(headerRow);
            table.appendChild(thead);

            var tbody = document.createElement("tbody");
            tbody.id = "recs-tbody-" + cat;
            table.appendChild(tbody);
            panel.appendChild(table);
            contentsContainer.appendChild(panel);

            // Init sort state
            if (!tabSortState[cat]) {
                tabSortState[cat] = { col: "priority_score", dir: "desc" };
            }

            // Sort header click
            headerRow.querySelectorAll("th[data-col]").forEach(function (th) {
                th.addEventListener("click", function () {
                    var state = tabSortState[cat];
                    if (state.col === th.dataset.col) {
                        state.dir = state.dir === "asc" ? "desc" : "asc";
                    } else {
                        state.col = th.dataset.col;
                        state.dir = "desc";
                    }
                    rebuildTabRows(cat, isAll);
                });
            });

            // Select-all listener
            selectAllCb.addEventListener("change", function () {
                var checked = selectAllCb.checked;
                tbody.querySelectorAll(".rec-check").forEach(function (cb) {
                    cb.checked = checked;
                });
                updateSelectedCount();
            });

            rebuildTabRows(cat, isAll);
        });

        updateSelectedCount();
    }

    function rebuildTabRows(cat, isAll) {
        var items = isAll ? currentRecs.slice() : currentRecs.filter(function (r) {
            return r.category === cat;
        });
        var state = tabSortState[cat];

        items.sort(function (a, b) {
            var va = a[state.col], vb = b[state.col];
            if (typeof va === "string" || typeof vb === "string") {
                va = va != null ? String(va) : "";
                vb = vb != null ? String(vb) : "";
                return state.dir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
            }
            if (va == null) va = 0;
            if (vb == null) vb = 0;
            return state.dir === "asc" ? va - vb : vb - va;
        });

        // Update header sort indicators
        var panel = document.getElementById("recs-panel-" + cat);
        panel.querySelectorAll("th[data-col]").forEach(function (th) {
            th.classList.remove("sorted-asc", "sorted-desc");
            if (th.dataset.col === state.col) {
                th.classList.add(state.dir === "asc" ? "sorted-asc" : "sorted-desc");
            }
        });

        var tbody = document.getElementById("recs-tbody-" + cat);
        tbody.innerHTML = "";

        items.forEach(function (r) {
            var tr = document.createElement("tr");
            tr.dataset.path = r.path;

            var catCol = isAll
                ? '<td><span class="cat-badge ' + escapeAttr(r.category) + '">' +
                  escapeHtml(CATEGORY_LABELS[r.category] || r.category) + '</span></td>'
                : '';

            tr.innerHTML =
                '<td class="col-check"><input type="checkbox" class="rec-check" data-path="' +
                escapeAttr(r.path) + '"></td>' +
                catCol +
                '<td class="col-path" title="' + escapeAttr(r.path) + '">' +
                escapeHtml(displayPath(r.path)) + '</td>' +
                '<td class="col-size">' + escapeHtml(r.size_human) + '</td>' +
                '<td class="col-age">' + escapeHtml(r.age_days != null ? r.age_days + "d" : "\u2014") + '</td>' +
                '<td class="col-score">' + escapeHtml(String(r.priority_score)) + '</td>' +
                '<td class="col-reason" title="' + escapeAttr(r.reason) + '">' +
                escapeHtml(displayReason(r.reason)) + '</td>';
            tbody.appendChild(tr);
        });

        // Checkbox listeners
        tbody.querySelectorAll(".rec-check").forEach(function (cb) {
            cb.addEventListener("change", updateSelectedCount);
        });
    }

    /** Scroll to a recommendation row by path, switching to the right category tab. */
    function scrollToRecommendation(path, category) {
        // First try the specific category tab, then fall back to "all"
        var targetTab = category || "all";
        var tabBtn = document.querySelector('.recs-tab[data-recs-tab="' + targetTab + '"]');
        if (tabBtn) tabBtn.click();

        // Small delay to let the tab panel become visible
        setTimeout(function () {
            var row = document.querySelector(
                '#recs-panel-' + targetTab + ' tr[data-path="' + CSS.escape(path) + '"]'
            );
            if (!row) {
                // Fall back to "all" tab
                var allBtn = document.querySelector('.recs-tab[data-recs-tab="all"]');
                if (allBtn && targetTab !== "all") {
                    allBtn.click();
                    row = document.querySelector(
                        '#recs-panel-all tr[data-path="' + CSS.escape(path) + '"]'
                    );
                }
            }
            if (row) {
                row.scrollIntoView({ behavior: "smooth", block: "center" });
                row.classList.add("highlight");
                setTimeout(function () { row.classList.remove("highlight"); }, 2000);
            }
        }, 50);
    }

    // ── Path elide toggle ─────────────────────────────────────
    document.getElementById("elide-paths").addEventListener("change", function () {
        elidePathsEnabled = this.checked;
        // Re-render rows in all tab panels without rebuilding tabs
        document.querySelectorAll(".recs-tab").forEach(function (tab) {
            var cat = tab.dataset.recsTab;
            var isAll = cat === "all";
            rebuildTabRows(cat, isAll);
        });
    });

    function updateSelectedCount() {
        // Collect unique selected paths across all tab panels
        var selectedPaths = new Set();
        document.querySelectorAll(".rec-check:checked").forEach(function (cb) {
            selectedPaths.add(cb.dataset.path);
        });
        document.getElementById("selected-count").textContent =
            selectedPaths.size + " selected";
        document.getElementById("dl-script-btn").disabled = selectedPaths.size === 0;
    }

    // Download script
    document.getElementById("dl-script-btn").addEventListener("click", function () {
        var pathSet = new Set();
        document.querySelectorAll(".rec-check:checked").forEach(function (cb) {
            pathSet.add(cb.dataset.path);
        });
        var paths = Array.from(pathSet);
        if (paths.length === 0) return;
        var params = new URLSearchParams();
        paths.forEach(function (p) { params.append("paths", p); });
        fetch("/api/scan/script?" + params.toString())
            .then(function (r) {
                if (!r.ok) throw new Error("Server returned " + r.status);
                var disposition = r.headers.get("content-disposition") || "";
                var match = disposition.match(/filename=([^\s;]+)/);
                var filename = match ? match[1] : "cleanup.sh";
                return r.blob().then(function (blob) {
                    var url = URL.createObjectURL(blob);
                    var a = document.createElement("a");
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                });
            })
            .catch(function (err) {
                showAlert("Failed to download script: " + err.message);
            });
    });

    // New scan button
    document.getElementById("new-scan-btn").addEventListener("click", function () {
        fetch("/api/scan/reset", { method: "POST" })
            .then(function () {
                resultsSection.classList.remove("active");
                scanBtn.textContent = "Start Scan";
                scanBtn.disabled = false;
            });
    });

    // ── Exit Button ────────────────────────────────────────────
    var exitModal = document.getElementById("exit-modal");

    function showExitModal() {
        exitModal.classList.remove("hidden");
        requestAnimationFrame(function () { exitModal.classList.add("active"); });
    }

    function hideExitModal() {
        exitModal.classList.remove("active");
        setTimeout(function () { exitModal.classList.add("hidden"); }, 150);
    }

    function doShutdown() {
        fetch("/api/shutdown", { method: "POST" })
            .then(function () {
                document.body.innerHTML =
                    '<div class="app" style="display:flex;align-items:center;justify-content:center;' +
                    'height:100vh"><p style="color:var(--text-muted)">Server stopped. You can close this tab.</p></div>';
            })
            .catch(function () {
                document.body.innerHTML =
                    '<div class="app" style="display:flex;align-items:center;justify-content:center;' +
                    'height:100vh"><p style="color:var(--text-muted)">Server stopped. You can close this tab.</p></div>';
            });
    }

    document.getElementById("exit-btn").addEventListener("click", showExitModal);
    document.getElementById("exit-cancel-btn").addEventListener("click", hideExitModal);
    document.getElementById("exit-confirm-btn").addEventListener("click", function () {
        hideExitModal();
        doShutdown();
    });
    exitModal.addEventListener("click", function (e) {
        if (e.target === exitModal) hideExitModal();
    });

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

    function escapeAttr(s) {
        return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;");
    }
})();
