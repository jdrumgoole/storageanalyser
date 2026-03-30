/* Cross-environment dedup tab logic */
(function () {
    "use strict";

    var alertBox = document.getElementById("dedup-alert-box");
    var alertMsg = document.getElementById("dedup-alert-msg");
    var progressEl = document.getElementById("dedup-progress");
    var resultsEl = document.getElementById("dedup-results");

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

    // ── Load stats ───────────────────────────────────────────
    function loadStats() {
        fetch("/api/dedup/stats")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                document.getElementById("dedup-scan-count").textContent = data.scan_count;
                document.getElementById("dedup-file-count").textContent =
                    data.file_count.toLocaleString();
                document.getElementById("dedup-checksummed").textContent =
                    data.checksummed.toLocaleString();
                document.getElementById("dedup-sources").textContent =
                    data.sources.length > 0 ? data.sources.join(", ") : "None";

                // Enable/disable buttons based on state
                var checksumBtn = document.getElementById("dedup-checksum-btn");
                var findBtn = document.getElementById("dedup-find-btn");
                checksumBtn.disabled = data.file_count === 0 || data.computing_checksums;
                findBtn.disabled = data.checksummed === 0;

                if (data.computing_checksums) {
                    checksumBtn.textContent = "Computing...";
                    progressEl.classList.add("active");
                    setTimeout(loadStats, 2000);
                } else {
                    checksumBtn.textContent = "Compute Checksums";
                    progressEl.classList.remove("active");
                }
            });
    }

    // Load stats when the dedup tab becomes active
    document.querySelector('.tab[data-tab="dedup"]').addEventListener("click", function () {
        loadStats();
    });

    // ── Compute checksums ────────────────────────────────────
    document.getElementById("dedup-checksum-btn").addEventListener("click", function () {
        hideAlert();
        this.disabled = true;
        this.textContent = "Computing...";
        document.getElementById("dedup-progress-label").textContent =
            "Computing MD5 checksums for dedup candidates...";
        progressEl.classList.add("active");

        fetch("/api/dedup/checksum", { method: "POST" })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    showAlert(data.error);
                    progressEl.classList.remove("active");
                    return;
                }
                // Poll stats until computing is done
                pollUntilDone();
            })
            .catch(function (err) {
                showAlert("Failed: " + err.message);
                progressEl.classList.remove("active");
            });
    });

    function pollUntilDone() {
        fetch("/api/dedup/stats")
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.computing_checksums) {
                    document.getElementById("dedup-checksummed").textContent =
                        data.checksummed.toLocaleString();
                    setTimeout(pollUntilDone, 1500);
                } else {
                    progressEl.classList.remove("active");
                    loadStats();
                }
            });
    }

    // ── Find duplicates ──────────────────────────────────────
    document.getElementById("dedup-find-btn").addEventListener("click", function () {
        hideAlert();
        var minSizeKB = parseInt(document.getElementById("dedup-min-size").value) || 1;
        var minSize = minSizeKB * 1024;

        document.getElementById("dedup-progress-label").textContent = "Finding duplicates...";
        progressEl.classList.add("active");
        resultsEl.classList.remove("active");

        fetch("/api/dedup/results?min_size=" + minSize)
            .then(function (r) { return r.json(); })
            .then(function (data) {
                progressEl.classList.remove("active");
                renderResults(data);
            })
            .catch(function (err) {
                progressEl.classList.remove("active");
                showAlert("Failed: " + err.message);
            });
    });

    // ── Render results ───────────────────────────────────────
    function renderResults(data) {
        resultsEl.classList.add("active");
        document.getElementById("dedup-group-count").textContent = data.group_count;
        document.getElementById("dedup-savings").textContent = data.total_savings_human;

        var container = document.getElementById("dedup-groups");
        container.innerHTML = "";

        if (data.groups.length === 0) {
            container.innerHTML =
                '<p style="color:var(--text-muted);padding:16px">No duplicates found.</p>';
            return;
        }

        data.groups.forEach(function (group, i) {
            var card = document.createElement("div");
            card.className = "dedup-group";

            var header = document.createElement("div");
            header.className = "dedup-group-header";

            var title = document.createElement("span");
            title.className = "dedup-group-title";
            var label = group.cross_source ? " (cross-environment)" : "";
            title.textContent = group.count + " copies" + label;

            var badge = document.createElement("span");
            badge.className = "dedup-group-size";
            badge.textContent = group.size_human + " each \u2014 save " + group.savings_human;

            header.appendChild(title);
            header.appendChild(badge);
            card.appendChild(header);

            var table = document.createElement("table");
            table.className = "recs-table";
            table.style.marginTop = "8px";

            var thead = document.createElement("thead");
            thead.innerHTML =
                "<tr><th>Source</th><th>Name</th><th>Path / Link</th><th>Modified</th></tr>";
            table.appendChild(thead);

            var tbody = document.createElement("tbody");
            group.files.forEach(function (f) {
                var tr = document.createElement("tr");

                var sourceCell = document.createElement("td");
                var sourceBadge = document.createElement("span");
                sourceBadge.className = "source-badge " + f.source;
                sourceBadge.textContent = f.source;
                sourceCell.appendChild(sourceBadge);

                var nameCell = document.createElement("td");
                nameCell.textContent = f.name;
                nameCell.style.maxWidth = "250px";
                nameCell.style.wordBreak = "break-all";

                var pathCell = document.createElement("td");
                pathCell.style.maxWidth = "400px";
                pathCell.style.wordBreak = "break-all";
                pathCell.style.fontSize = "0.8rem";
                if (f.web_link) {
                    var a = document.createElement("a");
                    a.href = f.web_link;
                    a.target = "_blank";
                    a.textContent = "Open in Drive";
                    a.style.color = "var(--accent)";
                    a.style.textDecoration = "none";
                    pathCell.appendChild(a);
                } else {
                    pathCell.textContent = f.path;
                    pathCell.title = f.path;
                }

                var dateCell = document.createElement("td");
                dateCell.style.whiteSpace = "nowrap";
                dateCell.style.fontSize = "0.8rem";
                if (f.modified_time) {
                    dateCell.textContent = f.modified_time.substring(0, 10);
                }

                tr.appendChild(sourceCell);
                tr.appendChild(nameCell);
                tr.appendChild(pathCell);
                tr.appendChild(dateCell);
                tbody.appendChild(tr);
            });

            table.appendChild(tbody);
            card.appendChild(table);
            container.appendChild(card);
        });
    }
})();
