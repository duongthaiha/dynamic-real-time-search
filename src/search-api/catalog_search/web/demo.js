"use strict";
const byId = (id) => document.getElementById(id);
const form = byId("search-form");
let offset = 0;
let total = 0;
let activeRequest = null;
let currentBody = null;

function requestBody() {
  const low = byId("price-low").value;
  const high = byId("price-high").value;
  if ((low === "") !== (high === "")) throw new Error("Enter both minimum and maximum price, or clear both.");
  const refinements = [];
  for (const [id, field] of [["category", "category"], ["color", "attributes.color"], ["size", "attributes.size"]]) {
    const value = byId(id).value.trim();
    if (value) refinements.push({navigationName: field, type: "Value", value});
  }
  if (low !== "") {
    if (!Number.isFinite(Number(low)) || !Number.isFinite(Number(high)) || Number(low) > Number(high)) throw new Error("The minimum price must not exceed the maximum price.");
    refinements.push({navigationName: "price", type: "Range", low: Number(low), high: Number(high)});
  }
  return {query: byId("query").value.trim(), pageSize: Number(byId("page-size").value), refinements};
}

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}

function render(records) {
  const grid = byId("results");
  grid.replaceChildren();
  for (const record of records) {
    const card = document.createElement("article");
    card.className = "card";
    const photo = document.createElement("div");
    photo.className = "photo";
    const image = document.createElement("img");
    image.alt = record.title;
    image.loading = "lazy";
    image.referrerPolicy = "no-referrer";
    image.addEventListener("error", () => {image.hidden = true; photo.classList.add("failed");});
    if (record.imageUrl && /^https:\/\//.test(record.imageUrl)) image.src = record.imageUrl;
    else {image.hidden = true; photo.classList.add("failed");}
    photo.append(image);
    const details = document.createElement("div");
    details.className = "details";
    details.append(textElement("p", "meta", [record.category, record.attributes?.color].filter(Boolean).join(" / ")));
    details.append(textElement("h3", "title", record.title));
    const price = Number.isFinite(record.price) ? new Intl.NumberFormat("en-GB", {style: "currency", currency: record.currency}).format(record.price) : "Price unavailable";
    details.append(textElement("p", "price", price));
    details.append(textElement("p", "product-id", record.productId));
    card.append(photo, details);
    grid.append(card);
  }
}

function showError(message) {
  byId("error").textContent = message;
  byId("error").hidden = false;
}

async function search(nextOffset = 0) {
  if (activeRequest) activeRequest.abort();
  const controller = new AbortController();
  activeRequest = controller;
  const timer = setTimeout(() => controller.abort(), 15000);
  byId("error").hidden = true;
  byId("empty").hidden = true;
  byId("search-button").disabled = true;
  byId("previous").disabled = true;
  byId("next").disabled = true;
  byId("results").setAttribute("aria-busy", "true");
  byId("status").textContent = "Searching the live catalogue...";
  byId("timing").textContent = "";
  const started = performance.now();
  try {
    const body = {...currentBody, skip: nextOffset};
    const response = await fetch("/demo/search", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body), signal: controller.signal, credentials: "same-origin"});
    const data = await response.json();
    if (activeRequest !== controller) return;
    if (!response.ok) throw new Error(`${data.message} (${data.code}${data.requestId ? `; request ${data.requestId}` : ""})`);
    offset = data.skip;
    total = data.totalRecords;
    render(data.records);
    byId("result-heading").textContent = `${total.toLocaleString()} matching ${total === 1 ? "product" : "products"}`;
    byId("status").textContent = data.records.length ? `Showing ${offset + 1}-${offset + data.records.length} for "${data.query}"${data.degraded ? " (degraded ranking)" : ""}.` : `No products on this page for "${data.query}".`;
    byId("timing").textContent = `${Math.round(performance.now() - started)} ms`;
    byId("empty").hidden = data.records.length !== 0;
    byId("page-label").textContent = `Page ${Math.floor(offset / data.pageSize) + 1}`;
    byId("request-id").textContent = `Request: ${data.id}`;
    byId("previous").disabled = offset === 0;
    byId("next").disabled = offset + data.pageSize >= Math.min(total, 1000);
  } catch (error) {
    if (activeRequest !== controller) return;
    render([]);
    byId("status").textContent = "Search did not complete.";
    byId("request-id").textContent = "";
    showError(error.name === "AbortError" ? "Search timed out. Please retry." : error.message);
    console.error("Demo search failed", error);
  } finally {
    clearTimeout(timer);
    if (activeRequest === controller) {
      activeRequest = null;
      byId("search-button").disabled = false;
      byId("results").setAttribute("aria-busy", "false");
    }
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  try {currentBody = requestBody(); search(0);}
  catch (error) {showError(error.message);}
});
byId("previous").addEventListener("click", () => search(Math.max(0, offset - currentBody.pageSize)));
byId("next").addEventListener("click", () => search(offset + currentBody.pageSize));
currentBody = requestBody();
search(0);
