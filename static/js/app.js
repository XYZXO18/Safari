/**
 * Safari — Frontend Application
 * ==============================
 * Handles map, calendar, form interactions, and API calls.
 */

// ─── State ───────────────────────────────────────────────────────────────────
const state = {
    budget: 3000,
    currency: 'SAR',
    origin: 'riyadh',
    destination: 'coast',
    travelMode: 'car',
    vehicleType: 'default',
    days: 4,
    tripData: null,
    hospitalityType: 'all',
    selectedHotel: null,  // Track chosen hotel
};

// ─── Map Setup ───────────────────────────────────────────────────────────────
const map = L.map('map', {
    center: [24.0, 44.0],
    zoom: 6,
    zoomControl: false,
});

L.control.zoom({ position: 'topright' }).addTo(map);

// Dark map tiles
L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://carto.com/">CARTO</a>',
    maxZoom: 19,
}).addTo(map);

let routeLine = null;
let markers = [];

const CITY_COORDS = {};

// Load coordinates on start
fetch('/api/coords')
    .then(r => r.json())
    .then(data => Object.assign(CITY_COORDS, data));

// ─── DOM Elements ────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);

const budgetInput = $('budget-input');
const budgetSlider = $('budget-slider');
const budgetDisplay = $('budget-display');
const currencySelect = $('currency-select');
const originSelect = $('origin-select');
const vehicleSelect = $('vehicle-select');
const vehicleGroup = $('vehicle-group');
const daysValue = $('days-value');
const daysMinus = $('days-minus');
const daysPlus = $('days-plus');
const planBtn = $('plan-btn');
const tripForm = $('trip-form');
const loadingOverlay = $('loading-overlay');

// Map overlays
const tripInfo = $('trip-info');
const budgetBar = $('budget-bar');
const hotelGrid = $('hotel-comparison-grid');
const hotelCitySelect = $('hotel-city-select');

// Right panel
const itineraryList = $('itinerary-list');
const budgetDetails = $('budget-details');
const budgetTable = $('budget-table');
const warningsBox = $('warnings-box');

// ─── Format Number ───────────────────────────────────────────────────────────
function fmt(n) {
    return Math.round(n).toLocaleString('en-US');
}

// ─── Budget Input Sync ──────────────────────────────────────────────────────
budgetInput.addEventListener('input', () => {
    const v = parseInt(budgetInput.value) || 500;
    state.budget = v;
    budgetSlider.value = Math.min(v, 15000);
    budgetDisplay.textContent = fmt(v);
});

budgetSlider.addEventListener('input', () => {
    const v = parseInt(budgetSlider.value);
    state.budget = v;
    budgetInput.value = v;
    budgetDisplay.textContent = fmt(v);
});

currencySelect.addEventListener('change', () => {
    state.currency = currencySelect.value;
});

originSelect.addEventListener('change', () => {
    state.origin = originSelect.value;
});

// ─── View Switching ─────────────────────────────────────────────────────────
window.switchView = function(viewId) {
    // Hide all views
    document.querySelectorAll('.app-view').forEach(v => v.classList.add('hidden-view'));
    // Show target view
    const target = $(viewId);
    if (target) target.classList.remove('hidden-view');

    // Update indicators
    document.querySelectorAll('.active-indicator').forEach(i => i.classList.add('hidden'));
    const ind = $('ind-' + viewId);
    if (ind) ind.classList.remove('hidden');

    // Update nav active state
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => {
        const onclick = n.getAttribute('onclick');
        if (onclick && onclick.includes(viewId)) {
            n.classList.add('active');
        }
    });

    if (viewId === 'hotels-view') {
        loadHospitality();
    }

    // Fix map rendering when becoming visible
    if (viewId === 'map-view' && typeof map !== 'undefined') {
        setTimeout(() => map.invalidateSize(), 100);
    }
};

vehicleSelect.addEventListener('change', () => {
    state.vehicleType = vehicleSelect.value;
});

// ─── Vibe Cards ──────────────────────────────────────────────────────────────
document.querySelectorAll('.vibe-card').forEach(card => {
    card.addEventListener('click', () => {
        document.querySelectorAll('.vibe-card').forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        state.destination = card.dataset.vibe;
    });
});

// ─── Travel Mode ─────────────────────────────────────────────────────────────
document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.travelMode = btn.dataset.mode;
        vehicleGroup.classList.toggle('hidden', btn.dataset.mode !== 'car');
    });
});

// ─── Days ────────────────────────────────────────────────────────────────────
daysMinus.addEventListener('click', () => {
    if (state.days > 1) {
        state.days--;
        daysValue.textContent = state.days;
    }
});

daysPlus.addEventListener('click', () => {
    if (state.days < 30) {
        state.days++;
        daysValue.textContent = state.days;
    }
});

// ─── Calendar ────────────────────────────────────────────────────────────────
function renderCalendar(tripStartDay, tripDays) {
    const now = new Date();
    const year = now.getFullYear();
    const month = now.getMonth();
    const today = now.getDate();

    const startDay = tripStartDay || today + 1;

    $('cal-month').textContent = now.toLocaleString('en-US', { month: 'long', year: 'numeric' });

    const firstDayOfMonth = new Date(year, month, 1).getDay();
    const daysInMonth = new Date(year, month + 1, 0).getDate();

    const grid = $('cal-grid');
    grid.innerHTML = '';

    // Day headers
    ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'].forEach(d => {
        const cell = document.createElement('div');
        cell.className = 'cal-cell header';
        cell.textContent = d;
        grid.appendChild(cell);
    });

    // Empty cells before first day
    for (let i = 0; i < firstDayOfMonth; i++) {
        const cell = document.createElement('div');
        cell.className = 'cal-cell';
        grid.appendChild(cell);
    }

    // Day cells
    for (let d = 1; d <= daysInMonth; d++) {
        const cell = document.createElement('div');
        cell.className = 'cal-cell';
        cell.textContent = d;

        if (d === today) cell.classList.add('today');

        if (tripDays > 0) {
            const tripEnd = startDay + tripDays - 1;
            if (d >= startDay && d <= tripEnd) {
                const relativeDay = d - startDay + 1;
                cell.classList.add('trip-day');
                cell.style.cursor = 'pointer';
                cell.title = `Scroll to Day ${relativeDay}`;
                cell.onclick = () => {
                    const targetCard = document.getElementById(`day-card-${relativeDay}`);
                    if (targetCard) {
                        targetCard.scrollIntoView({ behavior: 'smooth', block: 'start' });
                        // Add temporary highlight effect
                        targetCard.style.boxShadow = '0 0 20px var(--accent)';
                        setTimeout(() => targetCard.style.boxShadow = '', 1000);
                    }
                };
                if (d === startDay) cell.classList.add('trip-start');
                if (d === tripEnd) cell.classList.add('trip-end');
            }
        }

        grid.appendChild(cell);
    }
}

// Initial calendar
renderCalendar(null, 0);

// ─── Map Helpers ─────────────────────────────────────────────────────────────
function clearMap() {
    markers.forEach(m => map.removeLayer(m));
    markers = [];
    if (routeLine) {
        map.removeLayer(routeLine);
        routeLine = null;
    }
}

// ─── Icon Factories ─────────────────────────────────────────────────────────
const DAY_COLORS = [
    '#8b5cf6','#06b6d4','#f59e0b','#10b981','#ec4899','#f97316','#6366f1'
];

function createDayMarker(day) {
    const color = DAY_COLORS[(day - 1) % DAY_COLORS.length];
    return L.divIcon({
        className: '',
        html: `<div class="day-marker day-marker-${day}" style="background:${color}">${day}</div>`,
        iconSize: [32, 32],
        iconAnchor: [16, 16],
        popupAnchor: [0, -18],
    });
}

function createHotelMarker() {
    return L.divIcon({
        className: '',
        html: `<div class="hotel-marker">🏨</div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
        popupAnchor: [0, -20],
    });
}

function createOriginMarker() {
    return L.divIcon({
        className: '',
        html: `<div class="hotel-marker" style="background:linear-gradient(135deg,#f97316,#fbbf24)">📍</div>`,
        iconSize: [34, 34],
        iconAnchor: [17, 17],
        popupAnchor: [0, -20],
    });
}

function drawRoute(originCoords, destCoords, originName, destName, data) {
    clearMap();

    const oLatLng = [originCoords.lat, originCoords.lng];
    const dLatLng = [destCoords.lat, destCoords.lng];

    const waypoints = [oLatLng];

    // Origin marker
    const originMarker = L.marker(oLatLng, { icon: createOriginMarker() })
        .addTo(map)
        .bindPopup(`
            <div class="popup-title">${originName}</div>
            <div class="popup-detail">Starting point</div>
        `);
    markers.push(originMarker);

    // Hotel markers (from hospitality or fallback)
    let addedHospitality = false;
    if (data.hospitality) {
        if (data.hospitality.hotels && data.hospitality.hotels.length > 0) {
            data.hospitality.hotels.forEach(h => {
                if (h.lat && h.lng) {
                    const hLatLng = [h.lat, h.lng];
                    waypoints.push(hLatLng);
                    const hotelMarker = L.marker(hLatLng, { icon: createHotelMarker() })
                        .addTo(map)
                        .bindPopup(`
                            <div class="popup-title">${h.name}</div>
                            <div class="popup-detail">${h.stars}★ Hotel</div>
                            <div class="popup-detail" style="color:var(--accent);">
                                ~${h.best_deal ? h.best_deal.final_price_sar : 0} SAR/night
                            </div>
                        `);
                    markers.push(hotelMarker);
                    addedHospitality = true;
                }
            });
        }
        if (data.hospitality.restaurants && data.hospitality.restaurants.length > 0) {
            data.hospitality.restaurants.forEach(r => {
                if (r.lat && r.lng) {
                    const rLatLng = [r.lat, r.lng];
                    const isCafe = r.cuisine && r.cuisine.toLowerCase().includes('cafe');
                    const emoji = isCafe ? '☕' : '🍽️';
                    const gradient = isCafe ? 'linear-gradient(135deg,#f59e0b,#ea580c)' : 'linear-gradient(135deg,#10b981,#06b6d4)';
                    const rMarker = L.marker(rLatLng, { icon: L.divIcon({
                        className: '',
                        html: `<div class="hotel-marker" style="background:${gradient};font-size:15px;">${emoji}</div>`,
                        iconSize: [32,32], iconAnchor: [16,16]
                    }) })
                        .addTo(map)
                        .bindPopup(`
                            <div class="popup-title">${r.name}</div>
                            <div class="popup-detail">${r.cuisine} | ★${r.rating}</div>
                        `);
                    markers.push(rMarker);
                }
            });
        }
    }

    // Fallback hotel/dest
    if (!addedHospitality) {
        const hotel = data.activities.hotel;
        if (hotel && hotel.lat && hotel.lng) {
            const hLatLng = [hotel.lat, hotel.lng];
            waypoints.push(hLatLng);
            const hotelMarker = L.marker(hLatLng, { icon: createHotelMarker() })
                .addTo(map)
                .bindPopup(`
                    <div class="popup-title">${hotel.name}</div>
                    <div class="popup-detail">Recommended Hotel</div>
                `);
            markers.push(hotelMarker);
        } else {
            waypoints.push(dLatLng);
            const destEmoji = { coast: '🏖️', mountains: '⛰️', desert: '🏜️', city: '🏙️' };
            const destMarker = L.marker(dLatLng, { icon: L.divIcon({
                className: '',
                html: `<div class="hotel-marker" style="background:linear-gradient(135deg,#06b6d4,#8b5cf6);font-size:16px;">${destEmoji[state.destination]||'📌'}</div>`,
                iconSize: [34,34], iconAnchor: [17,17]
            }) })
                .addTo(map)
                .bindPopup(`
                    <div class="popup-title">${destName}</div>
                    <div class="popup-detail">${data.activities.vibe}</div>
                    <div class="popup-detail">${fmt(data.transport.distance_km)} km from ${originName}</div>
                `);
            markers.push(destMarker);
        }
    }

    // Activity markers — day-numbered
    const daily = data.activities.daily_plan;
    Object.keys(daily).forEach(dayStr => {
        const day = parseInt(dayStr);
        daily[dayStr].forEach(act => {
            if (act && act.lat && act.lng) {
                const aLatLng = [act.lat, act.lng];
                waypoints.push(aLatLng);
                const isEvent = act.is_live_event;
                const isTrending = act.is_trending_spot;

                let markerIcon;
                if (isEvent || isTrending) {
                    const emoji = isEvent ? '🎪' : '🔥';
                    markerIcon = L.divIcon({
                        className: '',
                        html: `<div class="hotel-marker" style="background:linear-gradient(135deg,#f59e0b,#ec4899);font-size:15px;">${emoji}</div>`,
                        iconSize: [34,34], iconAnchor: [17,17]
                    });
                } else {
                    markerIcon = createDayMarker(day);
                }

                const timeStr = ((isEvent || isTrending) && act.time && act.time !== 'TBD')
                    ? `<div class="popup-detail" style="color:var(--accent);font-weight:bold;margin-top:4px;">🕒 ${act.time}</div>` : '';
                const typeLabel = isEvent ? 'Live Event' : isTrending ? 'Trending Spot' : `Day ${day}`;

                const actMarker = L.marker(aLatLng, { icon: markerIcon })
                    .addTo(map)
                    .bindPopup(`
                        <div class="popup-title">${act.name}</div>
                        <div class="popup-detail">${typeLabel}</div>
                        ${timeStr}
                    `);
                markers.push(actMarker);
            }
        });
    });

    // Route line connecting everything
    routeLine = L.polyline(waypoints, {
        color: '#8b5cf6',
        weight: 4,
        opacity: 0.8,
        dashArray: '10, 10',
    }).addTo(map);

    // Fit bounds to all waypoints
    const bounds = L.latLngBounds(waypoints);
    map.fitBounds(bounds, { padding: [80, 80] });
}

// ─── Generate Activity Times ────────────────────────────────────────────────
function getActivitySchedule(dayNum, activities, isFirstDay, isLastDay) {
    const schedule = [];
    let hour = 8;

    if (isFirstDay) {
        schedule.push({ time: '06:00', icon: '🚗', text: `Depart from ${state.origin.charAt(0).toUpperCase() + state.origin.slice(1)}` });
        hour = 14;
    }

    activities.forEach(act => {
        const isObj = typeof act === 'object';
        const name = isObj ? act.name : act;
        const isEvent = isObj && act.is_live_event;
        const isTrending = isObj && act.is_trending_spot;
        let icon;
        if (isEvent) icon = '🎪';
        else if (isTrending) icon = '🔥';
        else icon = '🎯';
        const time = ((isEvent || isTrending) && act.time && act.time !== "TBD") ? act.time : `${String(hour).padStart(2, '0')}:00`;
        const id = isObj ? act.id : null;
        const cost = isObj ? act.cost : 0;
        const whyGo = isObj ? act.why_go : '';
        const reviews = isObj ? act.reviews : [];
        const reviewCount = isObj ? act.review_count : 0;
        
        schedule.push({ time, icon, text: name, id, isEvent, isTrending, cost, dayNum, socialBuzz: isObj ? act.social_buzz : '', rating: isObj ? act.rating : 0, whyGo, reviews, reviewCount });
        hour += isLastDay ? 2 : 3;
    });

    if (isLastDay) {
        schedule.push({ time: `${String(Math.min(hour, 16)).padStart(2, '0')}:00`, icon: '🚗', text: `Return trip home` });
    }

    return schedule;
}

// ─── Render Itinerary ────────────────────────────────────────────────────────
function renderItinerary(data) {
    itineraryList.innerHTML = '';

    const days = data.budget.days;
    const daily = data.activities.daily_plan;
    const currency = data.budget.currency;
    const lodgingPending = data.budget.lodging.pending;
    const lodgingPerDay = lodgingPending ? 0 : data.budget.lodging.per_day;
    const perDay = lodgingPerDay + data.budget.food.per_day + data.budget.activities.per_day;

    for (let d = 1; d <= days; d++) {
        const acts = daily[String(d)] || [];
        const isFirst = d === 1;
        const isLast = d === days;
        const schedule = getActivitySchedule(d, acts, isFirst, isLast);

        const card = document.createElement('div');
        card.className = 'day-card';
        card.id = `day-card-${d}`;
        card.style.animationDelay = `${d * 0.08}s`;

        let activitiesHtml = schedule.map((s, index) => {
            const buzzTag = (s.isTrending && s.socialBuzz) ? `<div class="social-buzz-tag">📱 ${s.socialBuzz}</div>` : '';
            const deleteBtn = (s.isEvent || s.isTrending) ? `<button type="button" class="delete-btn" onclick="deleteEvent('${s.dayNum}', '${s.id}', ${s.cost})" title="Remove">🗑️</button>` : '';
            
            let legHtml = '';
            if (data.timeline && data.timeline[String(d)] && data.timeline[String(d)].legs) {
                const legs = data.timeline[String(d)].legs;
                if (index < legs.length) {
                    const leg = legs[index];
                    const mins = leg.time_minutes ? leg.time_minutes : null;
                    const timeTag = mins
                        ? `<span class="leg-time-pill">🕐 ${mins} min</span>`
                        : '';
                    legHtml = `
                    <div class="transit-leg">
                        <span class="leg-mode-icon">${leg.mode.includes('🚗') ? '🚗' : leg.mode.includes('🚕') ? '🚕' : '🚌'}</span>
                        <span class="leg-dist">📍 ${leg.dist.toFixed(1)} km</span>
                        ${timeTag}
                        ${leg.cost > 0 ? `<span class="leg-cost">💰 ${leg.cost.toFixed(0)} ${currency}</span>` : ''}
                    </div>`;
                }
            }

            let reviewsHtml = '';
            if (s.whyGo || (s.reviews && s.reviews.length > 0)) {
                reviewsHtml = `<div class="activity-reviews-panel" style="margin-top: 10px; padding: 12px; background: rgba(0,0,0,0.15); border-radius: 8px;">`;
                if (s.rating) {
                    reviewsHtml += `<div style="color:#fbbf24; font-weight:bold; margin-bottom:6px;">⭐ ${s.rating} (${s.reviewCount} reviews)</div>`;
                }
                if (s.whyGo) {
                    reviewsHtml += `<div style="font-size:0.95em; color:var(--text-secondary); margin-bottom:8px;"><em>Why go:</em> ${s.whyGo}</div>`;
                }
                if (s.reviews && s.reviews.length > 0) {
                    const rev = s.reviews[0]; // Show top review
                    reviewsHtml += `<div style="font-size:0.9em; border-left:2px solid var(--accent); padding-left:8px; color:#cbd5e1;">
                        " ${rev.text} " <br><span style="opacity:0.6;font-size:0.85em;">— ${rev.user} (⭐ ${rev.rating})</span>
                    </div>`;
                }
                reviewsHtml += `</div>`;
            }

            return `
            ${legHtml}
            <div class="activity-item ${s.isTrending ? 'trending-item' : ''} ${s.isEvent ? 'event-item' : ''}" style="align-items:flex-start; flex-direction:column;">
                <div style="display:flex; width:100%;">
                    <span class="activity-time">${s.time}</span>
                    <span class="activity-icon">${s.icon}</span>
                    <div style="flex:1">
                        <span>${s.text}</span>
                        ${buzzTag}
                    </div>
                    ${deleteBtn}
                </div>
                ${reviewsHtml}
            </div>
            `;
        }).join('');
        
        // Return-to-hotel transit leg
        if (data.timeline && data.timeline[String(d)] && data.timeline[String(d)].legs) {
            const legs = data.timeline[String(d)].legs;
            if (schedule.length < legs.length) {
                const leg = legs[legs.length - 1];
                const mins = leg.time_minutes || null;
                const timeTag = mins ? `<span class="leg-time-pill">🕐 ${mins} min</span>` : '';
                activitiesHtml += `
                <div class="transit-leg">
                    <span class="leg-mode-icon">🚗</span>
                    <span class="leg-dist">📍 ${leg.dist.toFixed(1)} km</span>
                    ${timeTag}
                    ${leg.cost > 0 ? `<span class="leg-cost">💰 ${leg.cost.toFixed(0)} ${currency}</span>` : ''}
                </div>`;
            }
        }
        
        let recommendationHtml = '';
        if (data.timeline && data.timeline[String(d)] && data.timeline[String(d)].recommendation) {
            recommendationHtml = `
                <div style="margin-top: 10px; padding: 12px; background: rgba(59, 130, 246, 0.1); border-left: 3px solid #3b82f6; font-size: 1.1em; border-radius: 4px; line-height: 1.5;">
                    ${data.timeline[String(d)].recommendation}
                </div>
            `;
        }

        // Add lodging and food info
        let lodgingLineHtml;
        if (lodgingPending) {
            lodgingLineHtml = `
            <div class="activity-item lodging-pending-item" style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05);cursor:pointer" onclick="switchView('hotels-view')">
                <span class="activity-time"></span>
                <span class="activity-icon">🏨</span>
                <span style="color:#fbbf24;">Lodging: <em>Go to Hospit. tab to choose →</em></span>
            </div>`;
        } else {
            lodgingLineHtml = `
            <div class="activity-item" style="margin-top:6px;padding-top:6px;border-top:1px solid rgba(255,255,255,0.05)">
                <span class="activity-time"></span>
                <span class="activity-icon">🏨</span>
                <span>Lodging: ~${fmt(data.budget.lodging.per_day)} ${currency}/night${state.selectedHotel ? ' — ' + state.selectedHotel.name : ''}</span>
            </div>`;
        }

        activitiesHtml += `
            ${recommendationHtml}
            ${lodgingLineHtml}
            <div class="activity-item">
                <span class="activity-time"></span>
                <span class="activity-icon">🍽️</span>
                <span>Meals: ~${fmt(data.budget.food.per_day)} ${currency}</span>
            </div>
        `;

        card.innerHTML = `
            <div class="day-header">
                <span class="day-number">Day ${d}${isFirst ? ' — Departure' : isLast ? ' — Return' : ''}</span>
                <span class="day-budget">~${fmt(perDay)} ${currency}</span>
            </div>
            <div class="day-activities">${activitiesHtml}</div>
        `;

        itineraryList.appendChild(card);
    }
}

// ─── Render Budget Details ───────────────────────────────────────────────────
function renderBudgetDetails(data) {
    const b = data.budget;
    const c = b.currency;
    const lodgingPending = b.lodging.pending;
    const lodgingLabel = lodgingPending ? '<span class="pending-pulse">⏳ Pending hotel selection</span>' : `${fmt(b.lodging.total)} ${c}`;
    const lodgingBarWidth = lodgingPending ? 0 : (b.lodging.total/b.total*100).toFixed(1);

    budgetTable.innerHTML = `
        <div class="budget-row">
            <span class="budget-row-label">🚗 Transport (round-trip)</span>
            <span class="budget-row-value">${fmt(b.transport)} ${c}</span>
        </div>
        <div class="budget-row ${lodgingPending ? 'pending-row' : ''}">
            <span class="budget-row-label">🏨 Lodging (${b.days} nights)</span>
            <span class="budget-row-value">${lodgingLabel}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🍽️ Food (${b.days} days)</span>
            <span class="budget-row-value">${fmt(b.food.total)} ${c}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🎯 Activities (${b.days} days)</span>
            <span class="budget-row-value">${fmt(b.activities.total)} ${c}</span>
        </div>
        <div class="budget-row">
            <span class="budget-row-label">🛡️ Emergency Buffer</span>
            <span class="budget-row-value">${fmt(b.buffer.total)} ${c}</span>
        </div>
        <div class="budget-row total">
            <span class="budget-row-label">Total Budget</span>
            <span class="budget-row-value">${fmt(b.total)} ${c}</span>
        </div>
        <div class="budget-vis-bar">
            <div class="vis-segment" style="width:${(b.transport/b.total*100).toFixed(1)}%;background:var(--color-transport)"></div>
            <div class="vis-segment" style="width:${lodgingBarWidth}%;background:var(--color-lodging)"></div>
            <div class="vis-segment" style="width:${(b.food.total/b.total*100).toFixed(1)}%;background:var(--color-food)"></div>
            <div class="vis-segment" style="width:${(b.activities.total/b.total*100).toFixed(1)}%;background:var(--color-activities)"></div>
            <div class="vis-segment" style="width:${(b.buffer.total/b.total*100).toFixed(1)}%;background:var(--color-buffer)"></div>
        </div>
    `;

    budgetDetails.classList.remove('hidden');
}

// ─── Update Map Overlays ────────────────────────────────────────────────────
function updateOverlays(data) {
    $('info-origin').textContent = data.map.origin_name;
    $('info-dest').textContent = data.map.dest_name;
    $('info-distance').textContent = fmt(data.transport.distance_km);
    $('info-time').textContent = data.transport.travel_time_str || '--';
    $('info-days').textContent = data.budget.days;
    $('info-cost').textContent = fmt(data.budget.total);
    $('info-currency').textContent = data.budget.currency;
    tripInfo.classList.remove('hidden');

    const c = data.budget.currency;
    const lodgingPending = data.budget.lodging.pending;
    const lodgingValText = lodgingPending ? '⏳ Pending' : `${fmt(data.budget.lodging.total)} ${c}`;
    $('val-transport').textContent = `${fmt(data.budget.transport)} ${c}`;
    $('val-lodging').textContent = lodgingValText;
    $('val-food').textContent = `${fmt(data.budget.food.total)} ${c}`;
    $('val-activities').textContent = `${fmt(data.budget.activities.total)} ${c}`;
    $('val-buffer').textContent = `${fmt(data.budget.buffer.total)} ${c}`;
    const transportIcon = data.transport.mode === 'flight' ? '✈️' : (data.transport.mode === 'train' ? '🚄' : (data.transport.mode === 'bus' ? '🚌' : '🚗'));
    const transportLabel = data.transport.mode.charAt(0).toUpperCase() + data.transport.mode.slice(1);
    
    // Update icons in segments
    const transportSeg = document.querySelector('#seg-transport .seg-label');
    if (transportSeg) transportSeg.textContent = transportIcon;
    
    const transportLogHeader = document.querySelector('.travel-dataset-panel h3');
    if (transportLogHeader) transportLogHeader.textContent = `${transportIcon} Complete Travel Log`;

    budgetBar.classList.remove('hidden');

    // Show simulation controls
    $('sim-controls').classList.remove('hidden');

    // Populate Transport Insight
    const t = data.transport;
    const insightPanel = $('transport-insight');
    const insightContent = $('transport-insight-content');
    if (insightPanel && insightContent) {
        const modeEmoji = t.mode.includes('🚗') ? '🚗' : t.mode.includes('✈️') ? '✈️' : t.mode.includes('🚂') ? '🚂' : '🚌';
        insightContent.innerHTML = `
            I've calculated the best route from <span class="insight-pill">${t.origin}</span> to <span class="insight-pill">${t.destination}</span>. 
            The total distance is <span class="insight-pill">${fmt(t.distance_km)} km</span>, taking approximately <span class="insight-pill">${t.travel_time_str}</span> via 
            <span class="insight-pill">${t.mode}</span>. 
            ${t.mode.includes('Drive') ? `Fuel costs for your <span class="insight-pill">${t.vehicle_type}</span> are estimated at <span class="insight-pill">${fmt(t.cost_round_trip)} ${c}</span> round-trip.` : ''}
            Check the itinerary for a detailed daily breakdown of local taxi and walking legs!
        `;
        insightPanel.classList.remove('hidden');
    }
}

// ─── Warnings ────────────────────────────────────────────────────────────────
function renderWarnings(data) {
    const warnings = data.budget.warnings || [];
    if (warnings.length === 0) {
        warningsBox.classList.add('hidden');
        return;
    }
    warningsBox.classList.remove('hidden');
    warningsBox.innerHTML = warnings.map(w => `
        <div class="warning-item">⚠️ ${w}</div>
    `).join('');
}

// ─── Travel Log ──────────────────────────────────────────────────────────────
function renderTravelLog(data) {
    const dataset = data.full_trip_dataset || [];
    const container = $('travel-dataset-panel');
    const content = $('travel-log-content');
    
    if (dataset.length === 0) {
        container.classList.add('hidden');
        return;
    }
    
    container.classList.remove('hidden');
    content.innerHTML = `
        <table class="travel-log-table">
            <thead>
                <tr>
                    <th>From</th>
                    <th>To</th>
                    <th>Mode</th>
                    <th>Dist</th>
                    <th>Time</th>
                </tr>
            </thead>
            <tbody>
                ${dataset.map(leg => {
                    const hrs = Math.floor(leg.time_minutes / 60);
                    const mins = leg.time_minutes % 60;
                    const timeStr = hrs > 0 ? `${hrs}h ${mins}m` : `${mins}m`;
                    const modeIcon = leg.mode.includes('flight') ? '✈️' : (leg.mode.includes('train') ? '🚄' : (leg.mode.includes('bus') ? '🚌' : '🚗'));
                    return `
                    <tr class="${leg.type === 'inter_city' ? 'inter-city-row' : ''}">
                        <td>${leg.from_name}</td>
                        <td>${leg.to_name}</td>
                        <td>${modeIcon} ${leg.mode}</td>
                        <td>${leg.dist.toFixed(1)} km</td>
                        <td>${timeStr}</td>
                    </tr>
                    `;
                }).join('')}
            </tbody>
        </table>
    `;
}

// ─── Hospitality View Logic ──────────────────────────────────────────────────
window.setHospitalityType = function(type, el) {
    state.hospitalityType = type;
    if (el) {
        const parent = el.parentElement;
        parent.querySelectorAll('.vibe-card').forEach(c => c.classList.remove('active'));
        el.classList.add('active');
    }
    loadHospitality();
};

async function loadHospitality() {
    const city = hotelCitySelect.value;
    const type = state.hospitalityType || 'all';
    hotelGrid.innerHTML = `<div class="loading">Loading hospitality...</div>`;

    // Check if a trip is active and lodging is still pending
    const tripActive = state.tripData && state.tripData.budget;
    const lodgingPending = tripActive && state.tripData.budget.lodging.pending;

    try {
        let results = [];
        if (type === 'all') {
            const res = await fetch(`/api/hospitality?city=${city}`);
            results = await res.json();
        } else {
            const res = await fetch(`/api/hospitality?city=${city}&type=${type}`);
            results = await res.json();
        }
        
        if (results.length === 0) {
            hotelGrid.innerHTML = `<div class="empty-state">No listings found for this city.</div>`;
            return;
        }

        // If trip is active, get hotel recommendation (closest to activities)
        let recommendedIdx = -1;
        let distances = [];
        let recReason = '';
        const allHotels = results.filter(i => i.type === 'hotel');
        if (tripActive && allHotels.length > 0) {
            try {
                const recRes = await fetch('/api/recommend-hotel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        hotels: allHotels,
                        activities_daily_plan: state.tripData.activities.daily_plan,
                    }),
                });
                if (recRes.ok) {
                    const recData = await recRes.json();
                    recommendedIdx = recData.recommended_hotel_index || 0;
                    distances = recData.distances_km || [];
                    recReason = recData.reason || '';
                }
            } catch (e) { console.warn('Rec failed:', e); }
        }

        // Track hotel index within the hotel-only list
        let hotelIdx = 0;

        // Helper to render a card
        const renderCard = (item) => {
            const isHotel = item.type === 'hotel';
            const isRest = item.type === 'restaurant';
            const isCafe = item.type === 'cafe';
            
            // For hotels: use live Almosafer price; for others use DB price
            const displayPrice = isHotel
                ? (item.live_price_sar || item.price || null)
                : (item.price || null);
            const priceLabel = isHotel ? 'SAR / night (Almosafer live)' : 'SAR (Avg/Person)';
            const icon = isHotel ? '🏨' : isRest ? '🍴' : '☕';
            const priceHtml = isHotel
                ? (displayPrice
                    ? `<div class="price-tag" style="color:#4ade80;">${Math.round(displayPrice)} <span style="font-size:11px;opacity:0.8;">${priceLabel}</span></div>
                       <div style="font-size:10px;color:var(--accent);margin-top:-6px;margin-bottom:8px;">📡 Live from Almosafer</div>`
                    : `<div class="price-tag" style="color:#f97316;">Price not available — <a href="${item.almosafer_url || 'https://www.almosafer.com'}" target="_blank" style="color:var(--accent);">Check Almosafer</a></div>`)
                : `<div class="price-tag">${displayPrice ? Math.round(displayPrice) : '—'} <span>${priceLabel}</span></div>`;

            // Hotel-specific trip-aware logic
            let isRec = false;
            let isSelected = false;
            let distKm = null;
            let currentHotelIdx = -1;
            let tripBtnHtml = '';
            let badgeHtml = '';
            let overBudgetHtml = '';

            if (isHotel) {
                currentHotelIdx = hotelIdx;
                isRec = currentHotelIdx === recommendedIdx;
                isSelected = state.selectedHotel && state.selectedHotel.name === item.name;
                distKm = distances[currentHotelIdx] !== undefined ? distances[currentHotelIdx] : null;
                hotelIdx++;

                if (isRec) {
                    badgeHtml = `<div class="rec-badge">📍 Closest to Activities</div>`;
                }
                if (isSelected) {
                    badgeHtml = `<div class="selected-badge">✅ Selected</div>`;
                }

                // Over-budget check
                if (tripActive && state.tripData.budget.lodging.max_per_day) {
                    const maxPD = state.tripData.budget.lodging.max_per_day;
                    if (item.price > maxPD * 1.2) {
                        overBudgetHtml = `<div class="over-budget-warn">⚠️ Exceeds suggested lodging budget (~${fmt(maxPD)} SAR/night)</div>`;
                    }
                }

                // Trip-aware button
                if (tripActive && lodgingPending) {
                    const days = state.tripData.budget.days;
                    const totalCost = Math.round(displayPrice || 0) * days;
                    const bookUrl = item.almosafer_url || 'https://www.almosafer.com';
                    tripBtnHtml = `
                        <div class="hotel-select-meta" style="margin-bottom:8px;">
                            <span>📅 ${days} nights = <strong>${fmt(totalCost)} SAR</strong></span>
                            ${distKm !== null ? `<span style="margin-left:8px;">📍 ${distKm.toFixed(1)} km from activities</span>` : ''}
                        </div>
                        ${overBudgetHtml}
                        <div style="display:flex;gap:8px;">
                        <button class="submit-btn" style="padding:10px; font-size:14px; background:linear-gradient(135deg,#4ade80,#10b981) !important; flex:1;"
                            onclick="selectHospitalityHotel(${currentHotelIdx})">
                            ${isSelected ? '✅ Selected' : '🏨 Select for Trip'}
                        </button>
                        <a href="${bookUrl}" target="_blank" style="padding:10px 12px; font-size:12px; background:rgba(139,92,246,0.2); border:1px solid rgba(139,92,246,0.4); border-radius:10px; color:var(--accent); text-decoration:none; display:flex; align-items:center;">
                            🔗 Almosafer
                        </a>
                        </div>`;
                } else if (tripActive && isSelected) {
                    tripBtnHtml = `
                        <button class="submit-btn" style="padding:10px; font-size:14px; background:linear-gradient(135deg,#10b981,#059669) !important;" disabled>
                            ✅ Selected for Trip
                        </button>`;
                } else {
                    const bookUrl = item.almosafer_url || 'https://www.almosafer.com';
                    tripBtnHtml = `
                        <div style="display:flex;gap:8px;">
                        <button class="submit-btn" style="padding:10px; font-size:14px; flex:1;"
                            onclick="askBooking(${item.id}, '${item.name.replace(/'/g, "\\'")}')">
                            Choose Hotel
                        </button>
                        <a href="${bookUrl}" target="_blank" style="padding:10px 12px; font-size:12px; background:rgba(139,92,246,0.2); border:1px solid rgba(139,92,246,0.4); border-radius:10px; color:var(--accent); text-decoration:none; display:flex; align-items:center;">
                            🔗 Almosafer
                        </a>
                        </div>`;
                }
            }
            
            let detailsHtml = '';
            if (isHotel) {
                detailsHtml = `
                <div class="availability" style="margin-bottom:15px; font-size:0.9em;">
                    <span style="background:rgba(56,189,248,0.1); padding:2px 8px; border-radius:10px; color:var(--accent); font-weight:600;">${item.empty_rooms}</span>
                    <span>rooms available</span>
                </div>`;
            } else {
                detailsHtml = `
                <div class="availability" style="margin-bottom:15px; font-size:0.9em;">
                    <span style="background:rgba(34, 197, 94, 0.1); padding:2px 8px; border-radius:10px; color:#22c55e; font-weight:600;">Open</span>
                    <span>${item.cuisine || 'Specialty'} | ${item.rating}⭐</span>
                </div>`;
            }

            const cardBorderColor = isHotel ? (isSelected ? '#4ade80' : isRec ? 'var(--accent)' : 'var(--accent)') : isRest ? '#22c55e' : '#f59e0b';
            const cardExtraClass = isHotel ? (isSelected ? 'hotel-selected' : isRec ? 'hotel-recommended' : '') : '';

            return `
            <div class="card ${cardExtraClass}" style="border-top: 3px solid ${cardBorderColor}; position:relative; overflow:hidden;">
                ${badgeHtml}
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                    <span style="font-size:12px; font-weight:bold; color:var(--text-muted); text-transform:uppercase;">${icon} ${item.type}</span>
                    <span style="font-size:14px;">${'★'.repeat(item.stars || 0)}${'⭐'.repeat(item.rating ? 1 : 0)}</span>
                </div>
                <h3>${item.name}</h3>
                ${priceHtml}
                ${detailsHtml}
                ${isHotel ? tripBtnHtml : `
                    <button class="submit-btn" style="padding:10px; font-size:14px;" 
                        onclick="alert('Opening menu for ${item.name.replace(/'/g, "\\'")}...')">
                        View Menu
                    </button>
                `}
            </div>
            `;
        };

        // Build the trip-aware header banner
        let headerHtml = '';
        if (lodgingPending) {
            const maxBudget = state.tripData.budget.lodging.max_per_day || 0;
            headerHtml = `
            <div style="grid-column:1/-1; padding:12px 16px; background:linear-gradient(135deg,rgba(251,191,36,0.1),rgba(245,158,11,0.05)); border:1px solid rgba(251,191,36,0.3); border-radius:12px; margin-bottom:10px;">
                <div style="font-size:15px; font-weight:700; color:#fbbf24; margin-bottom:4px;">⏳ Select a hotel for your trip</div>
                <div style="font-size:12px; color:var(--text-secondary);">Your lodging budget is pending. Pick a hotel to finalize your trip budget.
                ${maxBudget > 0 ? ` Suggested max: <strong style="color:var(--accent)">~${fmt(maxBudget)} SAR/night</strong>` : ''}
                </div>
            </div>`;
        }

        if (type === 'all') {
            const hotels = results.filter(i => i.type === 'hotel');
            const rests = results.filter(i => i.type === 'restaurant');
            const cafes = results.filter(i => i.type === 'cafe');
            
            let finalHtml = headerHtml;
            if (hotels.length) {
                finalHtml += `<div style="grid-column: 1/-1; margin-top:10px;"><h4 style="color:var(--accent)">🏨 Hotels</h4></div>`;
                finalHtml += hotels.map(renderCard).join('');
            }
            if (recReason && tripActive) {
                finalHtml += `<div style="grid-column:1/-1;" class="rec-reason">💡 ${recReason}</div>`;
            }
            if (rests.length) {
                finalHtml += `<div style="grid-column: 1/-1; margin-top:20px;"><h4 style="color:#22c55e">🍴 Top Restaurants</h4></div>`;
                finalHtml += rests.map(renderCard).join('');
            }
            if (cafes.length) {
                finalHtml += `<div style="grid-column: 1/-1; margin-top:20px;"><h4 style="color:#f59e0b">☕ Popular Cafes</h4></div>`;
                finalHtml += cafes.map(renderCard).join('');
            }
            hotelGrid.innerHTML = finalHtml;
        } else {
            hotelGrid.innerHTML = headerHtml + results.map(renderCard).join('');
        }
    } catch (e) {
        hotelGrid.innerHTML = `<div class="empty-state">Failed to load hospitality data.</div>`;
    }
}

let selectedHotelId = null;
function askBooking(id, name) {
    selectedHotelId = id;
    if (confirm(`Would you like to book a room at ${name}?`)) {
        confirmBooking();
    }
}

async function confirmBooking() {
    if (!selectedHotelId) return;
    try {
        const res = await fetch('/api/book', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({hotel_id: selectedHotelId})
        });
        if (res.ok) {
            alert('Hotel booked successfully!');
            loadHospitality();
        }
    } catch (e) {
        alert('Booking failed.');
    }
}

// ─── Select Hotel from Hospitality Tab for Trip ─────────────────────────────
// Called when user clicks "Select for Trip" on a hotel card in the Hospit. tab.
// Uses the DB-seeded hotel data and applies it to the active trip budget.
window.selectHospitalityHotel = function(hotelIdx) {
    if (!state.tripData) return;

    // Get the hotel list from the currently rendered grid
    // We need to re-fetch the hotels from the DOM data or use the cached results
    // Simplest: re-read from the hospitality API cache
    const city = hotelCitySelect.value;
    fetch(`/api/hospitality?city=${city}&type=hotel`)
        .then(r => r.json())
        .then(hotels => {
            if (!hotels || hotelIdx >= hotels.length) return;

            const h = hotels[hotelIdx];
            const price = Math.round(h.price);
            const days = state.tripData.budget.days;
            const totalBudget = state.tripData.budget.total;
            const transportCost = state.tripData.budget.transport;

            // Save selected hotel
            state.selectedHotel = {
                name: h.name,
                price_per_night: price,
                lat: h.lat,
                lng: h.lng,
                stars: h.stars,
                idx: hotelIdx,
            };

            // Recalculate budget:
            // Total → Transport → Hotel → remainder split into food/activities/buffer
            const lodgingTotal = price * days;
            const afterTransportAndHotel = totalBudget - transportCost - lodgingTotal;
            const remaining = Math.max(afterTransportAndHotel, 0);

            const foodTotal = remaining * 0.50;
            const activitiesTotal = remaining * 0.33;
            const bufferTotal = remaining * 0.17;

            const b = state.tripData.budget;
            b.lodging = {
                total: round2(lodgingTotal),
                per_day: round2(price),
                pending: false,
                max_budget: b.lodging.max_budget || lodgingTotal,
                max_per_day: b.lodging.max_per_day || price,
            };
            b.food = { total: round2(foodTotal), per_day: round2(foodTotal / days) };
            b.activities = { total: round2(activitiesTotal), per_day: round2(activitiesTotal / days) };
            b.buffer = { total: round2(bufferTotal), per_day: round2(bufferTotal / days) };
            b.remaining = round2(remaining);

            if (remaining <= 0) {
                b.warnings = b.warnings || [];
                if (!b.warnings.includes('Hotel cost + transport exceeds your total budget!')) {
                    b.warnings.push('Hotel cost + transport exceeds your total budget!');
                }
                b.is_feasible = false;
            }

            // Re-render all views
            renderItinerary(state.tripData);
            renderBudgetDetails(state.tripData);
            renderBudgetDetailsLeft(state.tripData);
            updateOverlays(state.tripData);
            renderWarnings(state.tripData);

            // Refresh the hospitality grid to show selected state
            loadHospitality();
        })
        .catch(e => console.error('Hotel selection failed:', e));
};

hotelCitySelect.addEventListener('change', loadHospitality);

// Initialize view listeners
function initViewListeners() {
    // Nav items are already handled by onclick="switchView(...)" in HTML,
    // but we can add more logic here if needed.
}
window.addEventListener('DOMContentLoaded', initViewListeners);
async function planTrip() {
    loadingOverlay.classList.remove('hidden');

    const payload = {
        budget: state.budget,
        currency: state.currency,
        origin: state.origin,
        destination: state.destination,
        travel_mode: state.travelMode,
        vehicle_type: state.vehicleType,
        days: state.days,
        interests: $('interests-input').value,
    };

    try {
        const response = await fetch('/api/plan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || 'Planning failed');
        }

        const data = await response.json();
        state.paths = data.paths;
        state.recommendation = data.recommendation;
        
        // Show path selection
        renderPathSelection(data.paths, data.recommendation);

    } catch (err) {
        alert('Safari encountered an error: ' + err.message);
    } finally {
        loadingOverlay.classList.add('hidden');
    }
}

// ─── Path Selection ──────────────────────────────────────────────────────────
function renderPathSelection(paths, recommendationIdx) {
    const grid = $('paths-grid');
    grid.innerHTML = '';
    
    paths.forEach((path, idx) => {
        const isRec = idx === recommendationIdx;
        const card = document.createElement('div');
        
        if (path.error) {
            card.className = `path-card error-path`;
            card.innerHTML = `
                <h3>${path.path_type} Path</h3>
                <div class="path-error-msg">⚠️ Failed: ${path.error}</div>
                <p style="font-size:12px; opacity:0.7;">This configuration is currently unavailable.</p>
            `;
            grid.appendChild(card);
            return;
        }

        const b = path.budget;
        const c = b.currency;
        
        let features = '';
        if (path.path_type === 'budget') {
            features = `<li>💰 Focused on free activities</li><li>🚌 Prioritizes public transit</li><li>🏨 Budget accommodations</li>`;
        } else if (path.path_type === 'balanced') {
            features = `<li>⚖️ Mix of free & paid activities</li><li>🚗 Comfortable transport</li><li>🏨 Mid-range hotels</li>`;
        } else {
            features = `<li>✨ Premium activities</li><li>🚕 Max convenience transport</li><li>🏨 Luxury accommodations</li>`;
        }

        card.className = `path-card ${isRec ? 'recommended' : ''}`;
        card.innerHTML = `
            <h3>${path.path_type} Path</h3>
            <div class="path-budget">~${fmt(b.total)} ${c}</div>
            <ul class="path-features">${features}</ul>
        `;
        card.addEventListener('click', () => selectPath(idx));
        grid.appendChild(card);
    });

    $('path-selection-overlay').classList.remove('hidden');
}

$('cancel-path-selection').addEventListener('click', () => {
    $('path-selection-overlay').classList.add('hidden');
});

function selectPath(idx) {
    $('path-selection-overlay').classList.add('hidden');
    
    // Switch panels
    $('trip-form').classList.add('hidden');
    $('results-panel').classList.remove('hidden');

    const data = state.paths[idx];
    state.tripData = data;

    // Draw map route
    drawRoute(data.map.origin, data.map.destination, data.map.origin_name, data.map.dest_name, data);

    // Update overlays
    updateOverlays(data);

    // Render itinerary (Right Panel)
    renderItinerary(data);

    // Render left panel results
    renderHospitalityDeals(data);
    renderWebResearch(data);
    renderBudgetDetailsLeft(data);

    // Render warnings
    renderWarnings(data);
    
    // Render travel log
    renderTravelLog(data);

    // Update calendar
    const today = new Date().getDate();
    renderCalendar(today + 1, state.days);

    // Setup simulation
    setupSimulation(data);

    // Reset hotel selection on new path and refresh Hospit. tab
    state.selectedHotel = null;
    if (data.map && data.map.dest_name) {
        const dest = data.map.dest_name.toLowerCase();
        for (let opt of hotelCitySelect.options) {
            if (opt.value === dest) {
                hotelCitySelect.value = dest;
                loadHospitality();
                break;
            }
        }
    }
}

$('edit-trip-btn').addEventListener('click', () => {
    $('results-panel').classList.add('hidden');
    $('trip-form').classList.remove('hidden');
});

function renderBudgetDetailsLeft(data) {
    const b = data.budget;
    const t = data.transport;
    const c = b.currency;
    const container = $('left-budget');
    if (!container) return;

    const isCar = t && (t.mode === 'car' || t.mode === 'driving');

    // Build fuel breakdown HTML (only for car mode)
    let fuelBreakdownHtml = '';
    if (isCar && t.breakdown) {
        // Parse breakdown string: "📊 Truck | Fuel (RON 91): 1100 km ÷ 8 km/L = 137.5 L @ 2.18 SAR/L"
        // We show a styled expandable card
        const vehicleLabel = (t.vehicle_type && t.vehicle_type !== 'default')
            ? t.vehicle_type.charAt(0).toUpperCase() + t.vehicle_type.slice(1)
            : 'Car';
        const litersOW = t.distance_km / (t.breakdown.match(/÷\s*([\d.]+)\s*km\/L/) ? parseFloat(t.breakdown.match(/÷\s*([\d.]+)\s*km\/L/)[1]) : 12);
        const kmPerLMatch = t.breakdown.match(/÷\s*([\d.]+)\s*km\/L/);
        const priceMatch  = t.breakdown.match(/@\s*([\d.]+)\s*SAR\/L/);
        const kmPerL  = kmPerLMatch  ? parseFloat(kmPerLMatch[1])  : '—';
        const pricePL = priceMatch   ? parseFloat(priceMatch[1])   : 2.18;
        const liters  = t.distance_km / (kmPerL || 12);

        fuelBreakdownHtml = `
        <div style="margin-top:4px;">
            <button id="fuel-toggle-btn" onclick="document.getElementById('fuel-breakdown-card').classList.toggle('hidden')" 
                style="background:none;border:none;color:var(--accent);font-size:12px;cursor:pointer;padding:2px 0;">
                ⛽ Show fuel details ▾
            </button>
            <div id="fuel-breakdown-card" class="hidden" style="
                margin-top:8px;
                padding:12px 14px;
                background: rgba(139,92,246,0.08);
                border: 1px solid rgba(139,92,246,0.25);
                border-radius:10px;
                font-size:12px;
                line-height:1.8;
                color:var(--text-secondary);
            ">
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;">
                    <span style="opacity:0.65;">Vehicle</span>
                    <span style="color:var(--text-primary);font-weight:600;">${vehicleLabel}</span>

                    <span style="opacity:0.65;">One-way distance</span>
                    <span style="color:var(--text-primary);">${fmt(t.distance_km)} km</span>

                    <span style="opacity:0.65;">Fuel efficiency</span>
                    <span style="color:var(--text-primary);">${kmPerL} km/L</span>

                    <span style="opacity:0.65;">Liters (one way)</span>
                    <span style="color:var(--text-primary);">${liters.toFixed(1)} L</span>

                    <span style="opacity:0.65;">Fuel price</span>
                    <span style="color:var(--text-primary);">2.18 SAR/L (RON 91)</span>

                    <span style="opacity:0.65;">One-way cost</span>
                    <span style="color:#fbbf24;">${fmt(t.cost_one_way)} ${c}</span>

                    <span style="opacity:0.65;">Round-trip cost</span>
                    <span style="color:#4ade80;font-weight:700;">${fmt(t.cost_round_trip)} ${c}</span>
                </div>
            </div>
        </div>
        `;
    }

    const transportIcon = t.mode === 'flight' ? '✈️' : (t.mode === 'train' ? '🚄' : (t.mode === 'bus' ? '🚌' : '🚗'));
    const transportLabel = t.mode.charAt(0).toUpperCase() + t.mode.slice(1);

    container.innerHTML = `
        <h3 style="margin-top:20px;margin-bottom:15px;color:var(--text-primary);font-size:22px;">💰 Budget Breakdown</h3>
        <div class="budget-row">
            <span class="budget-row-label">${transportIcon} ${transportLabel}</span>
            <span class="budget-row-value">${fmt(b.transport)} ${c}</span>
        </div>
        ${t.breakdown && !isCar ? `<div style="font-size:11px; color:var(--accent); margin-top:-8px; margin-bottom:12px; opacity:0.8; padding-left:24px;">${t.breakdown}</div>` : ''}
        ${fuelBreakdownHtml}
        <div class="budget-row ${b.lodging.pending ? 'pending-row' : ''}">
            <span class="budget-row-label">🏨 Lodging</span>
            <span class="budget-row-value">${b.lodging.pending ? '<span class="pending-pulse">⏳ Select hotel</span>' : fmt(b.lodging.total) + ' ' + c}</span>
        </div>
        <div class="budget-row"><span class="budget-row-label">🍽️ Food</span><span class="budget-row-value">${fmt(b.food.total)} ${c}</span></div>
        <div class="budget-row"><span class="budget-row-label">🎯 Activities</span><span class="budget-row-value">${fmt(b.activities.total)} ${c}</span></div>
        <div class="budget-row"><span class="budget-row-label">🛡️ Buffer</span><span class="budget-row-value">${fmt(b.buffer.total)} ${c}</span></div>
        <div class="budget-row total" style="margin-top:10px;padding-top:10px;border-top:1px solid rgba(255,255,255,0.1);font-weight:bold;font-size:18px;">
            <span class="budget-row-label">Total</span>
            <span class="budget-row-value">${fmt(b.total)} ${c}</span>
        </div>
    `;
}

// ─── Render Hospitality Deals ────────────────────────────────────────────────
function renderHospitalityDeals(data) {
    const container = $('left-hospitality');
    if (!container) return;

    if (!data.hospitality || (!data.hospitality.hotels.length && !data.hospitality.restaurants.length)) {
        container.innerHTML = '';
        return;
    }

    let html = '<h3 style="margin-bottom:15px;color:var(--text-primary);font-size:22px;">🏨 Recommended Places</h3>';

    if (data.hospitality.hotels && data.hospitality.hotels.length > 0) {
        html += `<div style="margin-bottom: 10px;"><strong>🏨 Hotels</strong></div>`;
        data.hospitality.hotels.slice(0, 3).forEach(h => {
            const bd = h.best_deal;
            html += `
                <div style="margin-bottom: 8px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">
                    <div><strong>${h.name}</strong> (${h.stars}★)</div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px;">
                        <span style="text-decoration: line-through; opacity: 0.6;">${bd.base_price_sar} SAR</span>
                        <span style="color: #4ade80; font-weight:bold;">${bd.final_price_sar} SAR</span>
                        <span style="color: var(--accent);">-${bd.discount_percent}% OFF</span>
                    </div>
                </div>
            `;
        });
    }

    if (data.hospitality.restaurants && data.hospitality.restaurants.length > 0) {
        html += `<div style="margin-top: 15px; margin-bottom: 10px;"><strong>🍽️ Restaurants</strong></div>`;
        data.hospitality.restaurants.slice(0, 3).forEach(r => {
            html += `
                <div style="margin-bottom: 8px; background: rgba(0,0,0,0.2); padding: 8px; border-radius: 4px;">
                    <div><strong>${r.name}</strong></div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px; opacity:0.8;">
                        <span>★ ${r.rating}</span>
                        <span>Tables: ${r.available_tables}/${r.total_tables}</span>
                    </div>
                </div>
            `;
        });
    }

    container.innerHTML = html;
}

// ─── Render Web Research Panel ──────────────────────────────────────────────
function renderWebResearch(data) {
    const research = data.web_research;
    const container = $('left-research');
    if (!container) return;

    if (!research) {
        container.innerHTML = '';
        return;
    }

    let html = '';

    // Weather
    if (research.weather_summary) {
        html += `
            <div class="research-section weather-section">
                <div class="research-header">🌤️ Current Weather</div>
                <p class="research-text">${research.weather_summary}</p>
            </div>
        `;
    }

    // Social Media Posts
    if (research.social_posts && research.social_posts.length > 0) {
        const platformIcons = {
            'x/twitter': '🐦', 'instagram': '📸',
            'tiktok': '🎵', 'reddit': '🔴', 'blog': '📝'
        };
        const platformColors = {
            'x/twitter': '#1DA1F2', 'instagram': '#E1306C',
            'tiktok': '#00f2ea', 'reddit': '#FF4500', 'blog': '#10B981'
        };
        html += `<div class="research-section">`;
        html += `<div class="research-header">📱 Social Media Buzz</div>`;
        research.social_posts.forEach(post => {
            const icon = platformIcons[post.platform] || '🌐';
            const color = platformColors[post.platform] || '#888';
            html += `
                <div class="social-post">
                    <div class="social-post-header">
                        <span class="platform-badge" style="background:${color}20;color:${color};border:1px solid ${color}40">
                            ${icon} ${post.platform}
                        </span>
                        <span class="social-author">@${post.author}</span>
                    </div>
                    <p class="social-content">${post.content}</p>
                    <div class="social-meta">
                        <span class="social-category">${post.category}</span>
                        ${post.likes ? `<span class="social-likes">❤️ ${post.likes.toLocaleString()}</span>` : ''}
                    </div>
                </div>
            `;
        });
        html += `</div>`;
    }

    // Trending Spots
    if (research.trending_spots && research.trending_spots.length > 0) {
        html += `<div class="research-section">`;
        html += `<div class="research-header">🔥 Trending Spots</div>`;
        research.trending_spots.forEach(spot => {
            const stars = spot.rating ? '⭐'.repeat(Math.round(spot.rating)) + ` (${spot.rating})` : '';
            const tagsHtml = (spot.tags || []).map(t => `<span class="spot-tag">${t}</span>`).join('');
            html += `
                <div class="trending-spot-card">
                    <div class="spot-header">
                        <span class="spot-name">${spot.name}</span>
                        <span class="spot-price">${spot.price_range}</span>
                    </div>
                    <p class="spot-description">${spot.description}</p>
                    ${stars ? `<div class="spot-rating">${stars}</div>` : ''}
                    ${spot.social_buzz ? `<div class="spot-buzz">📱 ${spot.social_buzz}</div>` : ''}
                    <div class="spot-tags">${tagsHtml}</div>
                    <div class="spot-cost">~${fmt(spot.estimated_cost_sar)} ${data.budget.currency}</div>
                </div>
            `;
        });
        html += `</div>`;
    }

    // Local Tips
    if (research.local_insights && research.local_insights.length > 0) {
        html += `<div class="research-section">`;
        html += `<div class="research-header">💡 Local Tips from the Web</div>`;
        research.local_insights.forEach(tip => {
            const categoryIcons = {
                'money_saving': '💰', 'safety': '🛡️',
                'culture': '🕌', 'weather': '🌤️', 'transport': '🚗'
            };
            const icon = categoryIcons[tip.category] || '💡';
            html += `
                <div class="local-tip">
                    <span class="tip-icon">${icon}</span>
                    <div class="tip-content">
                        <p>${tip.tip}</p>
                        <span class="tip-source">${tip.source}</span>
                    </div>
                </div>
            `;
        });
        html += `</div>`;
    }

    container.innerHTML = `<h3 style="margin-top:20px;margin-bottom:15px;color:var(--text-primary);font-size:22px;">🌐 Online Discoveries</h3>` + html;
}

// ─── Form Submit ─────────────────────────────────────────────────────────────
tripForm.addEventListener('submit', (e) => {
    e.preventDefault();
    planTrip();
});

// ─── Delete Event ────────────────────────────────────────────────────────────
window.deleteEvent = function(day, actId, cost) {
    if (!state.tripData) return;
    const daily = state.tripData.activities.daily_plan;
    if (daily[day]) {
        const idx = daily[day].findIndex(a => a.id === actId);
        if (idx !== -1) {
            daily[day].splice(idx, 1);
            state.tripData.budget.activities.total += cost;
            state.tripData.budget.activities.per_day = state.tripData.budget.activities.total / state.tripData.budget.days;
            renderItinerary(state.tripData);
            renderBudgetDetails(state.tripData);
            updateOverlays(state.tripData);
            drawRoute(state.tripData.map.origin, state.tripData.map.destination, state.tripData.map.origin_name, state.tripData.map.dest_name, state.tripData);
        }
    }
};

// ─── Route Simulation Engine ─────────────────────────────────────────────────
const sim = {
    playing: false,
    currentDay: '1',
    stepIdx: 0,
    timer: null,
    vehicleMarker: null,
    simLine: null,
    routes: {},   // simulation_routes from API
};

function setupSimulation(data) {
    sim.routes = data.simulation_routes || {};
    sim.playing = false;
    sim.stepIdx = 0;

    // Build day pills
    const pillContainer = $('sim-day-pills');
    pillContainer.innerHTML = '';
    Object.keys(sim.routes).forEach(dayStr => {
        const pill = document.createElement('button');
        pill.className = 'sim-day-pill' + (dayStr === '1' ? ' active' : '');
        pill.textContent = dayStr;
        pill.title = `Simulate Day ${dayStr}`;
        pill.addEventListener('click', () => {
            if (sim.playing) stopSimulation();
            document.querySelectorAll('.sim-day-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            sim.currentDay = dayStr;
            sim.stepIdx = 0;
            $('sim-status').textContent = `Day ${dayStr} ready — press ▶`;
            clearSimLine();
        });
        pillContainer.appendChild(pill);
    });

    if (Object.keys(sim.routes).length > 0) {
        sim.currentDay = Object.keys(sim.routes)[0];
        $('sim-status').textContent = `Press ▶ to simulate Day ${sim.currentDay}`;
    }

    $('sim-btn').onclick = () => {
        if (sim.playing) {
            stopSimulation();
        } else {
            startSimulation();
        }
    };
}

function clearSimLine() {
    if (sim.simLine) { map.removeLayer(sim.simLine); sim.simLine = null; }
}

function clearVehicle() {
    if (sim.vehicleMarker) { map.removeLayer(sim.vehicleMarker); sim.vehicleMarker = null; }
}

function startSimulation() {
    const points = sim.routes[sim.currentDay];
    if (!points || points.length < 2) {
        $('sim-status').textContent = 'No route data for this day.';
        return;
    }

    sim.playing = true;
    sim.stepIdx = 0;
    $('sim-btn').textContent = '⏹ Stop';
    $('sim-btn').classList.add('playing');
    clearSimLine();
    clearVehicle();

    // Create vehicle marker
    const vehicleIcon = L.divIcon({
        className: '',
        html: `<div class="sim-vehicle-marker">🚗</div>`,
        iconSize: [36, 36],
        iconAnchor: [18, 18],
    });

    const start = points[0];
    sim.vehicleMarker = L.marker([start.lat, start.lng], { icon: vehicleIcon, zIndexOffset: 1000 }).addTo(map);

    // Draw dim path for the day
    const latlngs = points.map(p => [p.lat, p.lng]);
    sim.simLine = L.polyline(latlngs, {
        color: '#fbbf24',
        weight: 3,
        opacity: 0.4,
        dashArray: '6,6',
    }).addTo(map);

    stepSimulation(points);
}

function stepSimulation(points) {
    if (!sim.playing) return;
    if (sim.stepIdx >= points.length) {
        stopSimulation();
        $('sim-status').textContent = `Day ${sim.currentDay} complete! 🏁`;
        return;
    }

    const pt = points[sim.stepIdx];
    const prevPt = sim.stepIdx > 0 ? points[sim.stepIdx - 1] : pt;

    // Move vehicle to this point
    if (sim.vehicleMarker) {
        sim.vehicleMarker.setLatLng([pt.lat, pt.lng]);
        map.panTo([pt.lat, pt.lng], { animate: true, duration: 0.6 });
    }

    // Update status label
    const typeEmoji = { hotel: '🏨', hotel_return: '🏨', activity: '' }[pt.type] || '';
    $('sim-status').textContent = `${typeEmoji} → ${pt.name}`;

    // Draw visited path segment (bright)
    const visitedPts = points.slice(0, sim.stepIdx + 1).map(p => [p.lat, p.lng]);
    if (sim.simLine) {
        sim.simLine.setStyle({ opacity: 0.35 });
    }

    sim.stepIdx++;

    // Delay based on travel time: use leg time if available, else ~1200ms
    const delay = 1200;
    sim.timer = setTimeout(() => stepSimulation(points), delay);
}

function stopSimulation() {
    sim.playing = false;
    if (sim.timer) clearTimeout(sim.timer);
    clearVehicle();
    $('sim-btn').textContent = '▶ Simulate';
    $('sim-btn').classList.remove('playing');
}

function round2(n) {
    return Math.round(n * 100) / 100;
}

