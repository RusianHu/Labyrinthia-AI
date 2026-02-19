(function (global) {
    'use strict';

    const VERSION = '0.3.0';
    const WALKABLE_TERRAINS = new Set(['floor', 'door', 'trap', 'treasure', 'stairs_up', 'stairs_down']);
    const PATCHABLE_TERRAINS = new Set(['floor', 'door', 'trap', 'treasure']);

    function clamp(value, min, max) {
        return Math.max(min, Math.min(max, value));
    }

    function tileKey(x, y) {
        return `${x},${y}`;
    }

    function parseKey(key) {
        const parts = key.split(',');
        return { x: Number(parts[0]), y: Number(parts[1]) };
    }

    function sortTileKeys(keys) {
        return keys.slice().sort((a, b) => {
            const pa = parseKey(a);
            const pb = parseKey(b);
            if (pa.y !== pb.y) {
                return pa.y - pb.y;
            }
            return pa.x - pb.x;
        });
    }

    function hashStringToUint32(input) {
        const text = String(input);
        let hash = 2166136261;
        for (let i = 0; i < text.length; i += 1) {
            hash ^= text.charCodeAt(i);
            hash = Math.imul(hash, 16777619);
        }
        return hash >>> 0;
    }

    function normalizeSeed(seedInput) {
        if (typeof seedInput === 'number' && Number.isFinite(seedInput)) {
            return (seedInput >>> 0);
        }
        if (typeof seedInput === 'string' && seedInput.trim() !== '') {
            return hashStringToUint32(seedInput.trim());
        }
        return hashStringToUint32('default-local-map-seed');
    }

    class SeededRng {
        constructor(seed) {
            this.state = normalizeSeed(seed) || 1;
        }

        next() {
            this.state |= 0;
            this.state = (this.state + 0x6D2B79F5) | 0;
            let t = Math.imul(this.state ^ (this.state >>> 15), 1 | this.state);
            t ^= t + Math.imul(t ^ (t >>> 7), 61 | t);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        }

        int(min, max) {
            const low = Math.ceil(min);
            const high = Math.floor(max);
            if (high <= low) {
                return low;
            }
            return low + Math.floor(this.next() * (high - low + 1));
        }

        bool(probability) {
            return this.next() < probability;
        }

        pick(array) {
            if (!array || array.length === 0) {
                return null;
            }
            return array[this.int(0, array.length - 1)];
        }
    }

    function defaultTile(x, y) {
        return {
            x,
            y,
            terrain: 'wall',
            is_explored: false,
            is_visible: false,
            items: [],
            character_id: null,
            room_type: '',
            room_id: null,
            has_event: false,
            event_type: '',
            event_data: {},
            is_event_hidden: true,
            event_triggered: false,
            items_collected: [],
            trap_detected: false,
            trap_disarmed: false
        };
    }

    function cloneMap(map) {
        const next = {
            id: map.id,
            name: map.name,
            description: map.description,
            width: map.width,
            height: map.height,
            depth: map.depth,
            floor_theme: map.floor_theme,
            tiles: {}
        };
        const keys = Object.keys(map.tiles || {});
        for (let i = 0; i < keys.length; i += 1) {
            const key = keys[i];
            next.tiles[key] = {
                ...map.tiles[key],
                items: Array.isArray(map.tiles[key].items) ? map.tiles[key].items.slice() : [],
                event_data: { ...(map.tiles[key].event_data || {}) },
                items_collected: Array.isArray(map.tiles[key].items_collected) ? map.tiles[key].items_collected.slice() : []
            };
        }
        return next;
    }

    class LocalMapGenerator {
        constructor(seedInput) {
            this.seedInput = seedInput;
            this.seed = normalizeSeed(seedInput);
            this.rng = new SeededRng(this.seed);
            this.roomCounter = 0;
            this.eventCounter = 0;
        }

        generate(rawSpec) {
            const spec = this._normalizeSpec(rawSpec);
            const map = this._createEmptyMap(spec);
            const rooms = this._generateRooms(spec);

            if (rooms.length === 0) {
                rooms.push(this._createFallbackRoom(spec));
            }

            this._carveRooms(map, rooms);
            this._connectRooms(map, rooms, spec.layout_style);
            this._assignRoomTypes(map, rooms, spec);
            this._ensureRoomTypeRequirements(rooms, spec);
            this._paintAllRoomTypes(map, rooms);

            const stairs = this._placeStairs(map, rooms, spec);
            this._placeSpecialFeatures(map, rooms, spec, stairs);
            const events = this._placeQuestEvents(map, rooms, spec);
            const monsterHints = this._buildMonsterHints(map, rooms, spec, stairs);
            const spawn = this._pickSpawn(map, rooms, stairs);

            const validation = this.validateMap(map, spec, spawn);
            const hash = this.hashMap(map);
            const metrics = this.collectMetrics(map, rooms, events, stairs);

            return {
                seed: this.seed,
                seed_input: String(this.seedInput ?? ''),
                spec,
                map,
                rooms,
                spawn,
                stairs,
                events,
                monster_hints: monsterHints,
                validation,
                metrics,
                hash,
                version: VERSION
            };
        }

        validateMap(map, spec, spawn) {
            const errors = [];
            const warnings = [];

            const floors = [];
            const stairsUp = [];
            const stairsDown = [];
            const roomTypeCount = {
                entrance: 0,
                normal: 0,
                boss: 0,
                treasure: 0,
                special: 0,
                corridor: 0
            };

            const keys = Object.keys(map.tiles);
            for (let i = 0; i < keys.length; i += 1) {
                const tile = map.tiles[keys[i]];
                if (tile.terrain === 'stairs_up') {
                    stairsUp.push(keys[i]);
                }
                if (tile.terrain === 'stairs_down') {
                    stairsDown.push(keys[i]);
                }
                if (WALKABLE_TERRAINS.has(tile.terrain)) {
                    floors.push(keys[i]);
                }
                if (tile.room_type && roomTypeCount[tile.room_type] !== undefined) {
                    roomTypeCount[tile.room_type] += 1;
                }
            }

            if (floors.length === 0) {
                errors.push('地图没有可行走地块');
            }

            if (spec.require_stairs_up && stairsUp.length === 0) {
                errors.push('缺少上楼梯');
            }
            if (spec.require_stairs_down && stairsDown.length === 0) {
                errors.push('缺少下楼梯');
            }

            if (spec.required_rooms.boss > 0 && roomTypeCount.boss === 0) {
                errors.push('缺少Boss房');
            }
            if (roomTypeCount.entrance === 0) {
                errors.push('缺少入口房');
            }

            const startKey = spawn ? tileKey(spawn.x, spawn.y) : null;
            if (!startKey || !map.tiles[startKey]) {
                errors.push('出生点无效');
            } else if (!WALKABLE_TERRAINS.has(map.tiles[startKey].terrain)) {
                errors.push('出生点不可行走');
            }

            const requiredTargets = [];
            if (spec.require_stairs_down) {
                for (let i = 0; i < stairsDown.length; i += 1) {
                    requiredTargets.push(stairsDown[i]);
                }
            }

            const mandatoryEventKeys = keys.filter((k) => {
                const t = map.tiles[k];
                return t.has_event && t.event_data && t.event_data.is_mandatory === true;
            });
            for (let i = 0; i < mandatoryEventKeys.length; i += 1) {
                requiredTargets.push(mandatoryEventKeys[i]);
            }

            if (startKey && requiredTargets.length > 0) {
                const reachable = this._floodFill(map, startKey);
                for (let i = 0; i < requiredTargets.length; i += 1) {
                    if (!reachable.has(requiredTargets[i])) {
                        errors.push(`关键目标不可达: ${requiredTargets[i]}`);
                    }
                }
            }

            if (floors.length < Math.max(20, Math.floor(map.width * map.height * 0.15))) {
                warnings.push('可行走面积偏小，探索体验可能受限');
            }

            return {
                ok: errors.length === 0,
                errors,
                warnings,
                floor_count: floors.length,
                required_target_count: requiredTargets.length
            };
        }

        collectMetrics(map, rooms, events, stairs) {
            const keys = Object.keys(map.tiles);
            let walkable = 0;
            let eventCount = 0;
            for (let i = 0; i < keys.length; i += 1) {
                const tile = map.tiles[keys[i]];
                if (WALKABLE_TERRAINS.has(tile.terrain)) {
                    walkable += 1;
                }
                if (tile.has_event) {
                    eventCount += 1;
                }
            }

            return {
                room_count: rooms.length,
                walkable_tiles: walkable,
                walkable_ratio: Number((walkable / (map.width * map.height)).toFixed(4)),
                event_count: eventCount,
                has_stairs_up: Boolean(stairs.up),
                has_stairs_down: Boolean(stairs.down)
            };
        }

        hashMap(map) {
            const keys = sortTileKeys(Object.keys(map.tiles));
            let text = `${map.width}|${map.height}|${map.depth}|${map.floor_theme}|`;
            for (let i = 0; i < keys.length; i += 1) {
                const tile = map.tiles[keys[i]];
                text += `${keys[i]}:${tile.terrain}:${tile.room_type}:${tile.has_event ? tile.event_type : '-'};`;
            }
            const hash = hashStringToUint32(text);
            return hash.toString(16).padStart(8, '0');
        }

        _normalizeSpec(input) {
            const spec = {
                title: input?.title || '本地任务',
                description: input?.description || '',
                quest_type: input?.quest_type || 'exploration',
                width: clamp(Number(input?.width ?? 32), 16, 80),
                height: clamp(Number(input?.height ?? 22), 16, 80),
                depth: clamp(Number(input?.depth ?? 1), 1, 99),
                max_depth: clamp(Number(input?.max_depth ?? 3), 1, 99),
                layout_style: input?.layout_style || 'standard',
                floor_theme: input?.floor_theme || 'normal',
                min_rooms: clamp(Number(input?.min_rooms ?? 6), 1, 20),
                max_rooms: clamp(Number(input?.max_rooms ?? 10), 2, 30),
                required_rooms: {
                    boss: clamp(Number(input?.required_rooms?.boss ?? 0), 0, 5),
                    treasure: clamp(Number(input?.required_rooms?.treasure ?? 0), 0, 6),
                    special: clamp(Number(input?.required_rooms?.special ?? 0), 0, 8)
                },
                require_stairs_up: Boolean(input?.require_stairs_up ?? Number(input?.depth ?? 1) > 1),
                require_stairs_down: Boolean(input?.require_stairs_down ?? Number(input?.depth ?? 1) < Number(input?.max_depth ?? 3)),
                quest_events: Array.isArray(input?.quest_events) ? input.quest_events : []
            };

            if (spec.max_rooms < spec.min_rooms) {
                spec.max_rooms = spec.min_rooms;
            }

            if (!['standard', 'linear', 'hub'].includes(spec.layout_style)) {
                spec.layout_style = 'standard';
            }

            return spec;
        }

        _createEmptyMap(spec) {
            const map = {
                id: `local-map-${this.seed.toString(16)}`,
                name: `${spec.title} - 第${spec.depth}层`,
                description: spec.description,
                width: spec.width,
                height: spec.height,
                depth: spec.depth,
                floor_theme: spec.floor_theme,
                tiles: {}
            };

            for (let y = 0; y < spec.height; y += 1) {
                for (let x = 0; x < spec.width; x += 1) {
                    map.tiles[tileKey(x, y)] = defaultTile(x, y);
                }
            }
            return map;
        }

        _nextRoomId() {
            this.roomCounter += 1;
            return `room-${this.roomCounter}`;
        }

        _createFallbackRoom(spec) {
            const width = clamp(Math.floor(spec.width / 3), 4, spec.width - 2);
            const height = clamp(Math.floor(spec.height / 3), 4, spec.height - 2);
            const x = Math.floor((spec.width - width) / 2);
            const y = Math.floor((spec.height - height) / 2);
            return {
                id: this._nextRoomId(),
                x,
                y,
                width,
                height,
                type: 'entrance'
            };
        }

        _generateRooms(spec) {
            const targetRooms = this.rng.int(spec.min_rooms, spec.max_rooms);
            if (spec.layout_style === 'linear') {
                return this._generateLinearRooms(spec, targetRooms);
            }
            if (spec.layout_style === 'hub') {
                return this._generateHubRooms(spec, targetRooms);
            }
            return this._generateStandardRooms(spec, targetRooms);
        }

        _generateLinearRooms(spec, targetRooms) {
            const rooms = [];
            const laneY = Math.floor(spec.height / 2);
            const step = Math.max(5, Math.floor((spec.width - 4) / Math.max(targetRooms, 2)));
            let cursorX = 1;

            for (let i = 0; i < targetRooms; i += 1) {
                const roomWidth = this.rng.int(4, 7);
                const roomHeight = this.rng.int(4, 7);
                const x = clamp(cursorX, 1, spec.width - roomWidth - 1);
                const y = clamp(laneY - Math.floor(roomHeight / 2) + this.rng.int(-1, 1), 1, spec.height - roomHeight - 1);
                const room = { id: this._nextRoomId(), x, y, width: roomWidth, height: roomHeight, type: 'normal' };
                if (!this._overlapsAny(room, rooms, 1)) {
                    rooms.push(room);
                }
                cursorX += step;
                if (cursorX >= spec.width - 4) {
                    break;
                }
            }
            return rooms;
        }

        _generateHubRooms(spec, targetRooms) {
            const rooms = [];
            const centerW = clamp(Math.floor(spec.width * 0.2), 4, 10);
            const centerH = clamp(Math.floor(spec.height * 0.2), 4, 10);
            const centerRoom = {
                id: this._nextRoomId(),
                x: Math.floor((spec.width - centerW) / 2),
                y: Math.floor((spec.height - centerH) / 2),
                width: centerW,
                height: centerH,
                type: 'entrance'
            };
            rooms.push(centerRoom);

            const anchors = [
                [2, 2],
                [spec.width - 8, 2],
                [2, spec.height - 8],
                [spec.width - 8, spec.height - 8],
                [Math.floor(spec.width / 2) - 3, 2],
                [Math.floor(spec.width / 2) - 3, spec.height - 8],
                [2, Math.floor(spec.height / 2) - 3],
                [spec.width - 8, Math.floor(spec.height / 2) - 3]
            ];

            while (rooms.length < targetRooms && anchors.length > 0) {
                const idx = this.rng.int(0, anchors.length - 1);
                const anchor = anchors.splice(idx, 1)[0];
                const roomWidth = this.rng.int(4, 7);
                const roomHeight = this.rng.int(4, 7);
                const room = {
                    id: this._nextRoomId(),
                    x: clamp(anchor[0] + this.rng.int(-1, 1), 1, spec.width - roomWidth - 1),
                    y: clamp(anchor[1] + this.rng.int(-1, 1), 1, spec.height - roomHeight - 1),
                    width: roomWidth,
                    height: roomHeight,
                    type: 'normal'
                };
                if (!this._overlapsAny(room, rooms, 1)) {
                    rooms.push(room);
                }
            }

            return rooms;
        }

        _generateStandardRooms(spec, targetRooms) {
            const rooms = [];
            let attempts = targetRooms * 20;

            while (rooms.length < targetRooms && attempts > 0) {
                attempts -= 1;
                const roomWidth = this.rng.int(4, 8);
                const roomHeight = this.rng.int(4, 8);
                const x = this.rng.int(1, spec.width - roomWidth - 1);
                const y = this.rng.int(1, spec.height - roomHeight - 1);
                const room = {
                    id: this._nextRoomId(),
                    x,
                    y,
                    width: roomWidth,
                    height: roomHeight,
                    type: 'normal'
                };
                if (!this._overlapsAny(room, rooms, 1)) {
                    rooms.push(room);
                }
            }

            return rooms;
        }

        _overlapsAny(room, rooms, margin) {
            for (let i = 0; i < rooms.length; i += 1) {
                if (this._roomsOverlap(room, rooms[i], margin)) {
                    return true;
                }
            }
            return false;
        }

        _roomsOverlap(a, b, margin) {
            const expand = margin || 0;
            return (
                a.x - expand < b.x + b.width + expand &&
                a.x + a.width + expand > b.x - expand &&
                a.y - expand < b.y + b.height + expand &&
                a.y + a.height + expand > b.y - expand
            );
        }

        _roomCenter(room) {
            return {
                x: room.x + Math.floor(room.width / 2),
                y: room.y + Math.floor(room.height / 2)
            };
        }

        _distance(a, b) {
            const ac = this._roomCenter(a);
            const bc = this._roomCenter(b);
            const dx = ac.x - bc.x;
            const dy = ac.y - bc.y;
            return Math.sqrt(dx * dx + dy * dy);
        }

        _carveRooms(map, rooms) {
            for (let i = 0; i < rooms.length; i += 1) {
                const room = rooms[i];
                for (let y = room.y; y < room.y + room.height; y += 1) {
                    for (let x = room.x; x < room.x + room.width; x += 1) {
                        const key = tileKey(x, y);
                        const tile = map.tiles[key];
                        tile.terrain = 'floor';
                        tile.room_id = room.id;
                        tile.room_type = room.type || 'normal';
                    }
                }
            }
        }

        _connectRooms(map, rooms, layoutStyle) {
            if (rooms.length <= 1) {
                return;
            }

            if (layoutStyle === 'linear') {
                for (let i = 0; i < rooms.length - 1; i += 1) {
                    this._connectTwoRooms(map, rooms[i], rooms[i + 1]);
                }
                return;
            }

            if (layoutStyle === 'hub') {
                const center = rooms[0];
                for (let i = 1; i < rooms.length; i += 1) {
                    this._connectTwoRooms(map, center, rooms[i]);
                }
                return;
            }

            const edges = [];
            for (let i = 0; i < rooms.length; i += 1) {
                for (let j = i + 1; j < rooms.length; j += 1) {
                    edges.push({
                        a: i,
                        b: j,
                        dist: this._distance(rooms[i], rooms[j])
                    });
                }
            }
            edges.sort((m, n) => m.dist - n.dist);

            const parent = [];
            for (let i = 0; i < rooms.length; i += 1) {
                parent.push(i);
            }

            const find = (x) => {
                if (parent[x] !== x) {
                    parent[x] = find(parent[x]);
                }
                return parent[x];
            };

            const union = (a, b) => {
                const pa = find(a);
                const pb = find(b);
                if (pa === pb) {
                    return false;
                }
                parent[pa] = pb;
                return true;
            };

            for (let i = 0; i < edges.length; i += 1) {
                const edge = edges[i];
                if (union(edge.a, edge.b)) {
                    this._connectTwoRooms(map, rooms[edge.a], rooms[edge.b]);
                }
            }

            for (let i = 0; i < edges.length; i += 1) {
                if (this.rng.bool(0.18)) {
                    this._connectTwoRooms(map, rooms[edges[i].a], rooms[edges[i].b]);
                }
            }
        }

        _connectTwoRooms(map, roomA, roomB) {
            const a = this._roomCenter(roomA);
            const b = this._roomCenter(roomB);

            const horizontalFirst = this.rng.bool(0.5);
            if (horizontalFirst) {
                this._carveCorridor(map, a.x, a.y, b.x, a.y);
                this._carveCorridor(map, b.x, a.y, b.x, b.y);
            } else {
                this._carveCorridor(map, a.x, a.y, a.x, b.y);
                this._carveCorridor(map, a.x, b.y, b.x, b.y);
            }
        }

        _carveCorridor(map, x1, y1, x2, y2) {
            if (x1 === x2) {
                const minY = Math.min(y1, y2);
                const maxY = Math.max(y1, y2);
                for (let y = minY; y <= maxY; y += 1) {
                    this._carveCorridorTile(map, x1, y);
                }
                return;
            }

            const minX = Math.min(x1, x2);
            const maxX = Math.max(x1, x2);
            for (let x = minX; x <= maxX; x += 1) {
                this._carveCorridorTile(map, x, y1);
            }
        }

        _carveCorridorTile(map, x, y) {
            const key = tileKey(x, y);
            const tile = map.tiles[key];
            if (!tile) {
                return;
            }
            tile.terrain = 'floor';
            if (!tile.room_type) {
                tile.room_type = 'corridor';
            }
        }

        _assignRoomTypes(map, rooms, spec) {
            if (rooms.length === 0) {
                return;
            }

            const entranceIndex = 0;
            rooms[entranceIndex].type = 'entrance';

            let bossIndex = -1;
            if (spec.required_rooms.boss > 0 && rooms.length > 1) {
                if (spec.layout_style === 'linear') {
                    bossIndex = rooms.length - 1;
                } else {
                    let farthest = -1;
                    let farthestDist = -1;
                    for (let i = 1; i < rooms.length; i += 1) {
                        const dist = this._distance(rooms[entranceIndex], rooms[i]);
                        if (dist > farthestDist) {
                            farthestDist = dist;
                            farthest = i;
                        }
                    }
                    bossIndex = farthest;
                }
                if (bossIndex >= 0) {
                    rooms[bossIndex].type = 'boss';
                }
            }

            const remaining = [];
            for (let i = 0; i < rooms.length; i += 1) {
                if (i !== entranceIndex && i !== bossIndex) {
                    remaining.push(i);
                }
            }

            const assignType = (count, type) => {
                let remainingCount = count;
                while (remainingCount > 0 && remaining.length > 0) {
                    const pickIndex = this.rng.int(0, remaining.length - 1);
                    const roomIndex = remaining.splice(pickIndex, 1)[0];
                    rooms[roomIndex].type = type;
                    remainingCount -= 1;
                }
            };

            assignType(spec.required_rooms.treasure, 'treasure');
            assignType(spec.required_rooms.special, 'special');

            for (let i = 0; i < remaining.length; i += 1) {
                rooms[remaining[i]].type = 'normal';
            }

            this._paintAllRoomTypes(map, rooms);
        }

        _paintAllRoomTypes(map, rooms) {
            for (let i = 0; i < rooms.length; i += 1) {
                this._paintRoomType(map, rooms[i]);
            }
        }

        _ensureRoomTypeRequirements(rooms, spec) {
            if (!Array.isArray(rooms) || rooms.length === 0) {
                return;
            }

            const required = {
                boss: clamp(Number(spec.required_rooms?.boss ?? 0), 0, 5),
                treasure: clamp(Number(spec.required_rooms?.treasure ?? 0), 0, 6),
                special: clamp(Number(spec.required_rooms?.special ?? 0), 0, 8)
            };

            const countTypes = () => {
                const counter = { entrance: 0, normal: 0, boss: 0, treasure: 0, special: 0, corridor: 0 };
                for (let i = 0; i < rooms.length; i += 1) {
                    const type = rooms[i].type || 'normal';
                    if (counter[type] !== undefined) {
                        counter[type] += 1;
                    }
                }
                return counter;
            };

            const pickReplaceCandidate = (counter) => {
                let fallback = -1;
                for (let i = 0; i < rooms.length; i += 1) {
                    const type = rooms[i].type;
                    if (type === 'entrance' || type === 'boss') {
                        continue;
                    }
                    if (type === 'normal') {
                        return i;
                    }
                    if (fallback < 0) {
                        fallback = i;
                    }
                }
                if (fallback >= 0) {
                    return fallback;
                }
                for (let i = rooms.length - 1; i >= 0; i -= 1) {
                    if (rooms[i].type !== 'entrance') {
                        return i;
                    }
                }
                return 0;
            };

            const counter = countTypes();

            const ensureType = (type, targetCount) => {
                while (counter[type] < targetCount) {
                    const candidate = pickReplaceCandidate(counter);
                    if (candidate < 0) {
                        break;
                    }
                    const oldType = rooms[candidate].type || 'normal';
                    if (oldType === type) {
                        break;
                    }
                    if (counter[oldType] !== undefined) {
                        counter[oldType] = Math.max(0, counter[oldType] - 1);
                    }
                    rooms[candidate].type = type;
                    counter[type] += 1;
                }
            };

            ensureType('boss', required.boss);
            ensureType('treasure', required.treasure);
            ensureType('special', required.special);
        }

        _paintRoomType(map, room) {
            for (let y = room.y; y < room.y + room.height; y += 1) {
                for (let x = room.x; x < room.x + room.width; x += 1) {
                    const key = tileKey(x, y);
                    const tile = map.tiles[key];
                    if (tile && tile.room_id === room.id) {
                        tile.room_type = room.type;
                    }
                }
            }
        }

        _placeStairs(map, rooms, spec) {
            const stairs = { up: null, down: null };
            if (rooms.length === 0) {
                return stairs;
            }

            const entranceRoom = rooms.find((room) => room.type === 'entrance') || rooms[0];
            const bossRoom = rooms.find((room) => room.type === 'boss') || rooms[rooms.length - 1];

            if (spec.require_stairs_up) {
                const pos = this._roomCenter(entranceRoom);
                this._setTerrain(map, pos.x, pos.y, 'stairs_up');
                stairs.up = pos;
            }

            if (spec.require_stairs_down) {
                let pos = this._roomCenter(bossRoom);
                if (stairs.up && pos.x === stairs.up.x && pos.y === stairs.up.y) {
                    pos = this._findNearbyFloor(map, pos, 3) || pos;
                }
                this._setTerrain(map, pos.x, pos.y, 'stairs_down');
                stairs.down = pos;
            }

            return stairs;
        }

        _placeSpecialFeatures(map, rooms, spec, stairs) {
            const floorKeys = [];
            const corridorKeys = [];
            const roomFloorByType = {
                boss: [],
                treasure: [],
                special: [],
                normal: [],
                entrance: []
            };
            const blocked = new Set();
            if (stairs?.up) {
                blocked.add(tileKey(stairs.up.x, stairs.up.y));
            }
            if (stairs?.down) {
                blocked.add(tileKey(stairs.down.x, stairs.down.y));
            }

            const keys = Object.keys(map.tiles);
            for (let i = 0; i < keys.length; i += 1) {
                const key = keys[i];
                if (blocked.has(key)) {
                    continue;
                }
                const tile = map.tiles[key];
                if (!tile || tile.terrain !== 'floor') {
                    continue;
                }
                floorKeys.push(key);
                if (tile.room_type === 'corridor') {
                    corridorKeys.push(key);
                } else if (roomFloorByType[tile.room_type]) {
                    roomFloorByType[tile.room_type].push(key);
                }
            }

            const pickFrom = (list) => {
                if (!list || list.length === 0) {
                    return null;
                }
                const idx = this.rng.int(0, list.length - 1);
                return list.splice(idx, 1)[0];
            };

            const removeFromAll = (key) => {
                if (!key) {
                    return;
                }
                const removeOne = (arr) => {
                    const idx = arr.indexOf(key);
                    if (idx >= 0) {
                        arr.splice(idx, 1);
                    }
                };
                removeOne(floorKeys);
                removeOne(corridorKeys);
                removeOne(roomFloorByType.boss);
                removeOne(roomFloorByType.treasure);
                removeOne(roomFloorByType.special);
                removeOne(roomFloorByType.normal);
                removeOne(roomFloorByType.entrance);
            };

            const putTerrain = (key, terrain) => {
                if (!key) {
                    return false;
                }
                const tile = map.tiles[key];
                if (!tile || tile.terrain !== 'floor') {
                    return false;
                }
                tile.terrain = terrain;
                removeFromAll(key);
                return true;
            };

            const questType = spec.quest_type || 'exploration';
            const treasureTarget = clamp(Number(spec.required_rooms?.treasure ?? 0) + 1, 0, 10);
            const trapTarget = clamp(1 + Math.floor((spec.depth || 1) / 2) + (questType === 'boss_fight' ? 1 : 0), 0, 12);

            for (let i = 0; i < treasureTarget; i += 1) {
                const key = pickFrom(roomFloorByType.treasure)
                    || pickFrom(roomFloorByType.special)
                    || pickFrom(roomFloorByType.normal)
                    || pickFrom(floorKeys);
                if (!putTerrain(key, 'treasure')) {
                    break;
                }
            }

            for (let i = 0; i < trapTarget; i += 1) {
                const key = pickFrom(corridorKeys)
                    || pickFrom(roomFloorByType.normal)
                    || pickFrom(roomFloorByType.special)
                    || pickFrom(floorKeys);
                if (!putTerrain(key, 'trap')) {
                    break;
                }
            }

            this._placeDoors(map, rooms, stairs);
        }

        _placeDoors(map, rooms, stairs) {
            const blocked = new Set();
            if (stairs?.up) {
                blocked.add(tileKey(stairs.up.x, stairs.up.y));
            }
            if (stairs?.down) {
                blocked.add(tileKey(stairs.down.x, stairs.down.y));
            }

            const candidates = [];
            const keys = Object.keys(map.tiles);
            for (let i = 0; i < keys.length; i += 1) {
                const key = keys[i];
                if (blocked.has(key)) {
                    continue;
                }
                const tile = map.tiles[key];
                if (!tile || tile.terrain !== 'floor') {
                    continue;
                }

                const pos = parseKey(key);
                const neighbors = [
                    map.tiles[tileKey(pos.x + 1, pos.y)],
                    map.tiles[tileKey(pos.x - 1, pos.y)],
                    map.tiles[tileKey(pos.x, pos.y + 1)],
                    map.tiles[tileKey(pos.x, pos.y - 1)]
                ];

                let wallCount = 0;
                let corridorTouch = 0;
                let roomTouch = 0;
                for (let j = 0; j < neighbors.length; j += 1) {
                    const n = neighbors[j];
                    if (!n) {
                        continue;
                    }
                    if (n.terrain === 'wall') {
                        wallCount += 1;
                    }
                    if (n.room_type === 'corridor') {
                        corridorTouch += 1;
                    } else if (n.room_type && n.room_type !== 'corridor') {
                        roomTouch += 1;
                    }
                }

                if (corridorTouch > 0 && roomTouch > 0 && wallCount >= 1) {
                    candidates.push(key);
                }
            }

            candidates.sort();
            const doorTarget = clamp(Math.floor(rooms.length * 0.8), 1, 18);
            let placed = 0;
            for (let i = 0; i < candidates.length && placed < doorTarget; i += 1) {
                const key = candidates[i];
                if (!this.rng.bool(0.62)) {
                    continue;
                }
                const tile = map.tiles[key];
                if (!tile || tile.terrain !== 'floor') {
                    continue;
                }
                tile.terrain = 'door';
                placed += 1;
            }
        }

        _setTerrain(map, x, y, terrain) {
            const key = tileKey(x, y);
            if (!map.tiles[key]) {
                return false;
            }
            map.tiles[key].terrain = terrain;
            return true;
        }

        _findNearbyFloor(map, origin, radius) {
            for (let r = 1; r <= radius; r += 1) {
                for (let dy = -r; dy <= r; dy += 1) {
                    for (let dx = -r; dx <= r; dx += 1) {
                        const x = origin.x + dx;
                        const y = origin.y + dy;
                        const key = tileKey(x, y);
                        const tile = map.tiles[key];
                        if (tile && tile.terrain === 'floor') {
                            return { x, y };
                        }
                    }
                }
            }
            return null;
        }

        _placeQuestEvents(map, rooms, spec) {
            const placed = [];
            const used = new Set();

            for (let i = 0; i < spec.quest_events.length; i += 1) {
                const eventPlan = spec.quest_events[i];
                const count = clamp(Number(eventPlan.count ?? 1), 1, 6);
                for (let j = 0; j < count; j += 1) {
                    const key = this._pickEventTileKey(map, rooms, eventPlan, used);
                    if (!key) {
                        continue;
                    }
                    const tile = map.tiles[key];
                    if (tile.terrain === 'trap' && (eventPlan.event_type || '') === 'trap') {
                        continue;
                    }
                    used.add(key);
                    tile.has_event = true;
                    tile.event_type = eventPlan.event_type || 'story';
                    tile.is_event_hidden = true;
                    tile.event_triggered = false;
                    tile.event_data = {
                        quest_event_id: `qe-${this.eventCounter++}`,
                        is_mandatory: Boolean(eventPlan.is_mandatory),
                        source: 'local_simulation',
                        title: eventPlan.title || `${eventPlan.event_type || 'story'} 事件`
                    };

                    if (tile.event_type === 'trap') {
                        tile.trap_detected = false;
                        tile.trap_disarmed = false;
                    }

                    placed.push({
                        key,
                        event_type: tile.event_type,
                        mandatory: tile.event_data.is_mandatory
                    });
                }
            }

            return placed;
        }

        _pickEventTileKey(map, rooms, eventPlan, usedKeys) {
            const preferredTypes = Array.isArray(eventPlan.preferred_room_types) && eventPlan.preferred_room_types.length > 0
                ? eventPlan.preferred_room_types
                : null;

            const candidates = [];
            const keys = Object.keys(map.tiles);
            for (let i = 0; i < keys.length; i += 1) {
                const key = keys[i];
                if (usedKeys.has(key)) {
                    continue;
                }
                const tile = map.tiles[key];
                if (!WALKABLE_TERRAINS.has(tile.terrain)) {
                    continue;
                }
                if (tile.terrain === 'trap' && (eventPlan.event_type || '') === 'trap') {
                    continue;
                }
                if (tile.terrain.startsWith('stairs')) {
                    continue;
                }
                if (tile.has_event) {
                    continue;
                }
                if (preferredTypes && preferredTypes.length > 0 && !preferredTypes.includes(tile.room_type)) {
                    continue;
                }
                candidates.push(key);
            }

            if (candidates.length === 0) {
                return null;
            }

            const sorted = sortTileKeys(candidates);
            return sorted[this.rng.int(0, sorted.length - 1)];
        }

        _pickSpawn(map, rooms, stairs) {
            if (stairs.up) {
                const around = this._findNearbyFloor(map, stairs.up, 3);
                if (around) {
                    return around;
                }
                return { ...stairs.up };
            }

            const entranceRoom = rooms.find((room) => room.type === 'entrance') || rooms[0];
            return this._roomCenter(entranceRoom);
        }

        _buildMonsterHints(map, rooms, spec, stairs) {
            const questType = spec.quest_type || 'exploration';
            const difficultyByQuest = {
                boss_fight: 'hard',
                exploration: 'medium',
                rescue: 'medium',
                investigation: 'normal'
            };

            const depth = clamp(Number(spec.depth ?? 1), 1, 99);
            const playerLevel = clamp(1 + depth * 2, 1, 30);
            const baseCount = clamp(Math.floor((spec.min_rooms + spec.max_rooms) / 10), 1, 6);
            const encounterCount = clamp(baseCount + (questType === 'boss_fight' ? 1 : 0), 1, 8);
            const bossCount = spec.required_rooms?.boss > 0 ? 1 : 0;

            const blocked = new Set();
            if (stairs?.up) {
                blocked.add(tileKey(stairs.up.x, stairs.up.y));
            }
            if (stairs?.down) {
                blocked.add(tileKey(stairs.down.x, stairs.down.y));
            }

            const floorCandidates = [];
            const roomCandidates = {
                boss: [],
                special: [],
                treasure: [],
                normal: [],
                corridor: []
            };

            const keys = Object.keys(map.tiles);
            for (let i = 0; i < keys.length; i += 1) {
                const key = keys[i];
                if (blocked.has(key)) {
                    continue;
                }
                const tile = map.tiles[key];
                if (!tile || !WALKABLE_TERRAINS.has(tile.terrain)) {
                    continue;
                }
                if (tile.terrain === 'stairs_up' || tile.terrain === 'stairs_down') {
                    continue;
                }
                floorCandidates.push(key);
                const type = tile.room_type || 'normal';
                if (roomCandidates[type]) {
                    roomCandidates[type].push(key);
                }
            }

            const used = new Set();
            const pickUnique = (lists) => {
                for (let i = 0; i < lists.length; i += 1) {
                    const arr = lists[i];
                    if (!arr || arr.length === 0) {
                        continue;
                    }
                    for (let j = 0; j < 16; j += 1) {
                        const key = arr[this.rng.int(0, arr.length - 1)];
                        if (!used.has(key)) {
                            used.add(key);
                            return key;
                        }
                    }
                    for (let j = 0; j < arr.length; j += 1) {
                        if (!used.has(arr[j])) {
                            used.add(arr[j]);
                            return arr[j];
                        }
                    }
                }
                return null;
            };

            const spawn_points = [];
            const encounterTargets = clamp(encounterCount, 1, floorCandidates.length);
            for (let i = 0; i < encounterTargets; i += 1) {
                const key = pickUnique([
                    roomCandidates.normal,
                    roomCandidates.corridor,
                    roomCandidates.special,
                    floorCandidates
                ]);
                if (!key) {
                    break;
                }
                const pos = parseKey(key);
                spawn_points.push({
                    x: pos.x,
                    y: pos.y,
                    role: 'encounter'
                });
            }

            if (bossCount > 0) {
                const bossKey = pickUnique([
                    roomCandidates.boss,
                    roomCandidates.special,
                    roomCandidates.normal,
                    floorCandidates
                ]);
                if (bossKey) {
                    const pos = parseKey(bossKey);
                    spawn_points.push({
                        x: pos.x,
                        y: pos.y,
                        role: 'boss'
                    });
                }
            }

            return {
                source: 'local_map_generator',
                spawn_strategy: 'llm_generate_by_positions',
                recommended_player_level: playerLevel,
                encounter_difficulty: difficultyByQuest[questType] || 'medium',
                encounter_count: encounterCount,
                boss_count: bossCount,
                spawn_points,
                llm_context: {
                    quest_type: questType,
                    map_title: spec.title,
                    map_depth: depth,
                    floor_theme: spec.floor_theme,
                    width: spec.width,
                    height: spec.height
                }
            };
        }

        _floodFill(map, startKey) {
            const visited = new Set();
            const queue = [startKey];
            visited.add(startKey);

            while (queue.length > 0) {
                const current = queue.shift();
                const pos = parseKey(current);
                const neighbors = [
                    tileKey(pos.x + 1, pos.y),
                    tileKey(pos.x - 1, pos.y),
                    tileKey(pos.x, pos.y + 1),
                    tileKey(pos.x, pos.y - 1)
                ];

                for (let i = 0; i < neighbors.length; i += 1) {
                    const key = neighbors[i];
                    if (visited.has(key)) {
                        continue;
                    }
                    const tile = map.tiles[key];
                    if (!tile) {
                        continue;
                    }
                    if (!WALKABLE_TERRAINS.has(tile.terrain)) {
                        continue;
                    }
                    visited.add(key);
                    queue.push(key);
                }
            }

            return visited;
        }
    }

    function buildMapSpecFromQuestRequest(requestInput) {
        const request = requestInput || {};
        const questType = request.quest_type || 'exploration';
        const depth = clamp(Number(request.depth ?? 1), 1, 99);
        const maxDepth = clamp(Number(request.max_depth ?? 3), 1, 99);

        let layoutStyle = 'standard';
        let minRooms = 6;
        let maxRooms = 10;
        let bossRooms = 0;
        let treasureRooms = 1;
        let specialRooms = 1;

        if (questType === 'boss_fight') {
            layoutStyle = 'linear';
            minRooms = 5;
            maxRooms = 8;
            bossRooms = 1;
            specialRooms = 1;
        } else if (questType === 'exploration') {
            layoutStyle = 'hub';
            minRooms = 7;
            maxRooms = 12;
            treasureRooms = 2;
            specialRooms = 2;
        } else if (questType === 'rescue' || questType === 'investigation') {
            layoutStyle = 'standard';
            minRooms = 6;
            maxRooms = 11;
            specialRooms = 2;
        }

        if (depth >= maxDepth) {
            bossRooms = Math.max(1, bossRooms);
            layoutStyle = 'linear';
        }

        const providedEvents = Array.isArray(request.special_events) ? request.special_events : [];
        const events = [];

        for (let i = 0; i < providedEvents.length; i += 1) {
            const raw = providedEvents[i] || {};
            events.push({
                event_type: raw.event_type || 'story',
                title: raw.name || raw.title || `任务事件${i + 1}`,
                count: 1,
                is_mandatory: Boolean(raw.is_mandatory ?? true),
                preferred_room_types: inferRoomTypesByEvent(raw.event_type || 'story')
            });
        }

        if (events.length === 0) {
            if (questType === 'boss_fight') {
                events.push({ event_type: 'combat', title: '前哨战', count: 1, is_mandatory: true, preferred_room_types: ['normal', 'corridor'] });
                events.push({ event_type: 'boss', title: 'Boss遭遇', count: 1, is_mandatory: true, preferred_room_types: ['boss'] });
            } else if (questType === 'exploration') {
                events.push({ event_type: 'story', title: '线索发现', count: 1, is_mandatory: true, preferred_room_types: ['special', 'treasure'] });
                events.push({ event_type: 'treasure', title: '隐藏宝箱', count: 1, is_mandatory: false, preferred_room_types: ['treasure', 'special'] });
            } else {
                events.push({ event_type: 'story', title: '关键节点', count: 1, is_mandatory: true, preferred_room_types: ['special', 'normal'] });
            }
            events.push({ event_type: 'trap', title: '风险陷阱', count: 1, is_mandatory: false, preferred_room_types: ['corridor', 'normal'] });
        }

        return {
            title: request.title || request.quest_title || '任务地图',
            description: request.description || '前端本地算法测试任务',
            quest_type: questType,
            width: clamp(Number(request.width ?? 32), 16, 80),
            height: clamp(Number(request.height ?? 22), 16, 80),
            depth,
            max_depth: maxDepth,
            layout_style: request.layout_style || layoutStyle,
            floor_theme: request.floor_theme || inferThemeByQuestType(questType),
            min_rooms: clamp(Number(request.min_rooms ?? minRooms), 2, 20),
            max_rooms: clamp(Number(request.max_rooms ?? maxRooms), 3, 30),
            required_rooms: {
                boss: clamp(Number(request.required_rooms?.boss ?? bossRooms), 0, 5),
                treasure: clamp(Number(request.required_rooms?.treasure ?? treasureRooms), 0, 6),
                special: clamp(Number(request.required_rooms?.special ?? specialRooms), 0, 8)
            },
            require_stairs_up: Boolean(request.require_stairs_up ?? depth > 1),
            require_stairs_down: Boolean(request.require_stairs_down ?? depth < maxDepth),
            quest_events: events
        };
    }

    function inferThemeByQuestType(questType) {
        if (questType === 'exploration') {
            return 'abandoned';
        }
        if (questType === 'boss_fight') {
            return 'combat';
        }
        if (questType === 'rescue') {
            return 'cave';
        }
        return 'normal';
    }

    function inferRoomTypesByEvent(eventType) {
        if (eventType === 'boss') {
            return ['boss'];
        }
        if (eventType === 'treasure') {
            return ['treasure', 'special'];
        }
        if (eventType === 'trap') {
            return ['corridor', 'normal'];
        }
        if (eventType === 'combat') {
            return ['normal', 'corridor', 'special'];
        }
        return ['special', 'normal', 'treasure'];
    }

    function createScenarioLibrary() {
        return [
            {
                id: 'boss_final',
                name: 'Boss终局战',
                request: {
                    title: '黑曜守卫讨伐',
                    quest_type: 'boss_fight',
                    description: '玩家已接近任务终点，需要在深层区域击败目标Boss。',
                    depth: 3,
                    max_depth: 3,
                    width: 34,
                    height: 20,
                    special_events: [
                        { event_type: 'combat', name: '精英守卫', is_mandatory: true },
                        { event_type: 'boss', name: '黑曜守卫', is_mandatory: true }
                    ]
                }
            },
            {
                id: 'explore_ruins',
                name: '遗迹探索',
                request: {
                    title: '失落碑文调查',
                    quest_type: 'exploration',
                    description: '探索多分支遗迹并找回关键线索。',
                    depth: 1,
                    max_depth: 3,
                    width: 36,
                    height: 24,
                    special_events: [
                        { event_type: 'story', name: '碑文残片', is_mandatory: true },
                        { event_type: 'treasure', name: '古代储藏间', is_mandatory: false }
                    ]
                }
            },
            {
                id: 'rescue_mission',
                name: '救援任务',
                request: {
                    title: '营地失踪者救援',
                    quest_type: 'rescue',
                    description: '在复杂洞窟中定位并救援被困人员。',
                    depth: 2,
                    max_depth: 4,
                    width: 32,
                    height: 22,
                    special_events: [
                        { event_type: 'story', name: '求救信号', is_mandatory: true },
                        { event_type: 'trap', name: '塌方陷阱', is_mandatory: false }
                    ]
                }
            }
        ];
    }

    function cloneRequest(request) {
        if (!request || typeof request !== 'object') {
            return {};
        }
        return JSON.parse(JSON.stringify(request));
    }

    function createRandomizedScenarioBatch(baseScenarios, count, seedBase) {
        const scenarios = Array.isArray(baseScenarios) ? baseScenarios : createScenarioLibrary();
        const total = clamp(Number(count ?? 0), 0, 300);
        if (total <= 0 || scenarios.length === 0) {
            return [];
        }

        const rng = new SeededRng(seedBase || 'local-random-scenario-batch');
        const questTypes = ['exploration', 'boss_fight', 'rescue', 'investigation'];
        const randomEvents = ['story', 'combat', 'trap', 'treasure'];
        const randomized = [];

        for (let i = 0; i < total; i += 1) {
            const base = scenarios[rng.int(0, scenarios.length - 1)] || scenarios[0];
            const request = cloneRequest(base.request);

            const baseWidth = clamp(Number(request.width ?? 32), 16, 80);
            const baseHeight = clamp(Number(request.height ?? 22), 16, 80);
            request.width = clamp(baseWidth + rng.int(-4, 12), 16, 80);
            request.height = clamp(baseHeight + rng.int(-4, 10), 16, 80);

            const baseMaxDepth = clamp(Number(request.max_depth ?? 3), 1, 99);
            request.max_depth = clamp(baseMaxDepth + rng.int(-1, 2), 1, 99);
            request.depth = clamp(Number(request.depth ?? 1) + rng.int(-1, 1), 1, request.max_depth);

            if (rng.bool(0.35)) {
                request.quest_type = questTypes[rng.int(0, questTypes.length - 1)];
            }

            const specialEvents = Array.isArray(request.special_events) ? request.special_events.slice(0, 4) : [];
            if (specialEvents.length === 0 || rng.bool(0.55)) {
                specialEvents.push({
                    event_type: randomEvents[rng.int(0, randomEvents.length - 1)],
                    name: `随机事件${i + 1}`,
                    is_mandatory: rng.bool(0.5)
                });
            }
            request.special_events = specialEvents;

            request.title = `${request.title || base.name || '随机任务'} [随机#${i + 1}]`;

            randomized.push({
                id: `${base.id || 'scenario'}_rnd_${i + 1}`,
                name: `${base.name || '随机场景'} #${i + 1}`,
                request,
                is_randomized: true,
                source_scenario: base.id || 'unknown'
            });
        }

        return randomized;
    }

    function createSimulatedLLMPatches(map, spec, seedInput) {
        const rng = new SeededRng(`${seedInput || 'patch'}-${spec.title}-${spec.depth}`);
        const keys = Object.keys(map.tiles);
        const floorKeys = keys.filter((key) => {
            const tile = map.tiles[key];
            return tile.terrain === 'floor' && !tile.has_event;
        });

        const corridorKeys = keys.filter((key) => {
            const tile = map.tiles[key];
            return tile.room_type === 'corridor' && tile.terrain === 'floor' && !tile.has_event;
        });

        const specialKeys = keys.filter((key) => {
            const tile = map.tiles[key];
            return tile.room_type === 'special' && tile.terrain === 'floor' && !tile.has_event;
        });

        const patches = [];

        const addStoryKey = specialKeys.length > 0 ? specialKeys[rng.int(0, specialKeys.length - 1)] : (floorKeys.length > 0 ? floorKeys[rng.int(0, floorKeys.length - 1)] : null);
        if (addStoryKey) {
            patches.push({
                op: 'set_event',
                key: addStoryKey,
                event_type: 'story',
                event_data: {
                    source: 'llm_patch',
                    title: '剧情插入点',
                    is_mandatory: false
                },
                reason: '根据任务上下文补充剧情触发点'
            });
        }

        if (corridorKeys.length > 0) {
            const trapKey = corridorKeys[rng.int(0, corridorKeys.length - 1)];
            patches.push({
                op: 'set_event',
                key: trapKey,
                event_type: 'trap',
                event_data: {
                    source: 'llm_patch',
                    title: '路径压力陷阱',
                    is_mandatory: false,
                    detect_dc: 14,
                    disarm_dc: 16,
                    save_dc: 13
                },
                reason: '提高路线风险密度'
            });
        }

        const treasureKey = floorKeys.length > 0 ? floorKeys[rng.int(0, floorKeys.length - 1)] : null;
        if (treasureKey) {
            patches.push({
                op: 'set_tile_terrain',
                key: treasureKey,
                terrain: 'treasure',
                reason: '生成可选奖励点'
            });
        }

        return patches;
    }

    function applyPatchesWithValidation(map, spec, spawn, patches) {
        const workMap = cloneMap(map);
        const generator = new LocalMapGenerator('patch-validate');
        const accepted = [];
        const rejected = [];

        for (let i = 0; i < patches.length; i += 1) {
            const patch = patches[i];
            const tile = workMap.tiles[patch.key];
            if (!tile) {
                rejected.push({ patch, reason: '目标瓦片不存在' });
                continue;
            }

            const backup = {
                terrain: tile.terrain,
                has_event: tile.has_event,
                event_type: tile.event_type,
                event_data: { ...(tile.event_data || {}) },
                is_event_hidden: tile.is_event_hidden,
                trap_detected: tile.trap_detected,
                trap_disarmed: tile.trap_disarmed
            };

            let applyError = null;
            if (patch.op === 'set_tile_terrain') {
                if (!PATCHABLE_TERRAINS.has(patch.terrain)) {
                    applyError = `不允许设置地形: ${patch.terrain}`;
                } else if (tile.terrain === 'stairs_up' || tile.terrain === 'stairs_down') {
                    applyError = '禁止修改楼梯瓦片';
                } else {
                    tile.terrain = patch.terrain;
                }
            } else if (patch.op === 'set_event') {
                if (tile.terrain === 'stairs_up' || tile.terrain === 'stairs_down') {
                    applyError = '禁止在楼梯瓦片放置事件';
                } else {
                    tile.has_event = true;
                    tile.event_type = patch.event_type || 'story';
                    tile.event_data = {
                        ...(patch.event_data || {}),
                        source: 'llm_patch'
                    };
                    tile.is_event_hidden = true;
                }
            } else {
                applyError = `不支持的补丁操作: ${patch.op}`;
            }

            if (applyError) {
                rejected.push({ patch, reason: applyError });
                continue;
            }

            const check = generator.validateMap(workMap, spec, spawn);
            if (!check.ok) {
                tile.terrain = backup.terrain;
                tile.has_event = backup.has_event;
                tile.event_type = backup.event_type;
                tile.event_data = backup.event_data;
                tile.is_event_hidden = backup.is_event_hidden;
                tile.trap_detected = backup.trap_detected;
                tile.trap_disarmed = backup.trap_disarmed;
                rejected.push({ patch, reason: `应用后校验失败: ${check.errors.join(' | ')}` });
                continue;
            }

            accepted.push({ patch });
        }

        const finalValidation = generator.validateMap(workMap, spec, spawn);
        const finalHash = generator.hashMap(workMap);

        return {
            map: workMap,
            accepted,
            rejected,
            final_validation: finalValidation,
            final_hash: finalHash
        };
    }

    function collectCapabilityCoverage(map) {
        const coverage = {
            has_door: false,
            has_trap_terrain: false,
            has_treasure_terrain: false,
            trap_event_count: 0
        };

        const keys = Object.keys(map.tiles || {});
        for (let i = 0; i < keys.length; i += 1) {
            const tile = map.tiles[keys[i]];
            if (!tile) {
                continue;
            }
            if (tile.terrain === 'door') {
                coverage.has_door = true;
            }
            if (tile.terrain === 'trap') {
                coverage.has_trap_terrain = true;
            }
            if (tile.terrain === 'treasure') {
                coverage.has_treasure_terrain = true;
            }
            if (tile.has_event && tile.event_type === 'trap') {
                coverage.trap_event_count += 1;
            }
        }

        return coverage;
    }

    function runReliabilitySuite(options) {
        const baseScenarios = Array.isArray(options?.scenarios) ? options.scenarios : createScenarioLibrary();
        const runsPerScenario = clamp(Number(options?.runs_per_scenario ?? 30), 1, 500);
        const randomScenarioCount = clamp(Number(options?.random_scenario_count ?? 0), 0, 300);
        const randomScenarioSeed = String(options?.random_scenario_seed || 'local-random-suite-seed');
        const includePatches = Boolean(options?.include_patches ?? false);
        const maxFailureRecords = clamp(Number(options?.max_failure_records ?? 120), 10, 500);

        const randomScenarios = createRandomizedScenarioBatch(baseScenarios, randomScenarioCount, randomScenarioSeed);
        const scenarios = baseScenarios.concat(randomScenarios);

        let total = 0;
        let pass = 0;
        let deterministicPass = 0;
        let patchPass = 0;

        const failures = [];
        const scenarioStats = {};

        for (let s = 0; s < scenarios.length; s += 1) {
            const scenario = scenarios[s];
            const scenarioId = scenario.id || `scenario-${s + 1}`;
            if (!scenarioStats[scenarioId]) {
                scenarioStats[scenarioId] = {
                    scenario: scenarioId,
                    name: scenario.name || scenarioId,
                    source_scenario: scenario.source_scenario || scenarioId,
                    randomized: Boolean(scenario.is_randomized),
                    total: 0,
                    pass: 0,
                    fail: 0,
                    deterministic_pass: 0,
                    patch_pass: 0,
                    door_hits: 0,
                    trap_hits: 0,
                    treasure_hits: 0
                };
            }

            for (let i = 0; i < runsPerScenario; i += 1) {
                const seed = `${scenarioId}-run-${i}`;
                const spec = buildMapSpecFromQuestRequest(scenario.request);
                const genA = new LocalMapGenerator(seed);
                const genB = new LocalMapGenerator(seed);
                const resultA = genA.generate(spec);
                const resultB = genB.generate(spec);

                total += 1;
                scenarioStats[scenarioId].total += 1;

                const deterministic = resultA.hash === resultB.hash;
                if (deterministic) {
                    deterministicPass += 1;
                    scenarioStats[scenarioId].deterministic_pass += 1;
                }

                let patchSummary = null;
                let patchOk = true;
                if (includePatches) {
                    const patches = createSimulatedLLMPatches(resultA.map, resultA.spec, seed);
                    const patched = applyPatchesWithValidation(resultA.map, resultA.spec, resultA.spawn, patches);
                    patchOk = patched.final_validation.ok;
                    if (patchOk) {
                        patchPass += 1;
                        scenarioStats[scenarioId].patch_pass += 1;
                    }
                    patchSummary = {
                        total: patches.length,
                        accepted: patched.accepted.length,
                        rejected: patched.rejected.length,
                        final_validation: patched.final_validation,
                        final_hash: patched.final_hash
                    };
                }

                const capability = collectCapabilityCoverage(resultA.map);
                scenarioStats[scenarioId].door_hits = (scenarioStats[scenarioId].door_hits || 0) + (capability.has_door ? 1 : 0);
                scenarioStats[scenarioId].trap_hits = (scenarioStats[scenarioId].trap_hits || 0) + (capability.has_trap_terrain ? 1 : 0);
                scenarioStats[scenarioId].treasure_hits = (scenarioStats[scenarioId].treasure_hits || 0) + (capability.has_treasure_terrain ? 1 : 0);

                const generationOk = Boolean(resultA.validation && resultA.validation.ok);
                const passed = generationOk && deterministic && patchOk;

                if (passed) {
                    pass += 1;
                    scenarioStats[scenarioId].pass += 1;
                } else {
                    scenarioStats[scenarioId].fail += 1;
                    failures.push({
                        scenario: scenarioId,
                        scenario_name: scenario.name || scenarioId,
                        source_scenario: scenario.source_scenario || scenarioId,
                        randomized: Boolean(scenario.is_randomized),
                        seed,
                        deterministic,
                        generation_ok: generationOk,
                        hash_a: resultA.hash,
                        hash_b: resultB.hash,
                        errors: Array.isArray(resultA.validation?.errors) ? resultA.validation.errors.slice() : [],
                        warnings: Array.isArray(resultA.validation?.warnings) ? resultA.validation.warnings.slice() : [],
                        patch: patchSummary,
                        request_snapshot: cloneRequest(scenario.request)
                    });
                }
            }
        }

        const fail = total - pass;
        const scenarioBreakdown = Object.values(scenarioStats)
            .map((item) => ({
                ...item,
                pass_rate: item.total > 0 ? Number((item.pass / item.total).toFixed(4)) : 0,
                deterministic_rate: item.total > 0 ? Number((item.deterministic_pass / item.total).toFixed(4)) : 0,
                patch_rate: includePatches ? (item.total > 0 ? Number((item.patch_pass / item.total).toFixed(4)) : 0) : null,
                door_rate: item.total > 0 ? Number((item.door_hits / item.total).toFixed(4)) : 0,
                trap_terrain_rate: item.total > 0 ? Number((item.trap_hits / item.total).toFixed(4)) : 0,
                treasure_terrain_rate: item.total > 0 ? Number((item.treasure_hits / item.total).toFixed(4)) : 0
            }))
            .sort((a, b) => {
                if (b.fail !== a.fail) {
                    return b.fail - a.fail;
                }
                return a.scenario.localeCompare(b.scenario);
            });

        const limitedFailures = failures.slice(0, maxFailureRecords);
        const replayCases = limitedFailures.map((failure, index) => ({
            replay_id: index + 1,
            scenario: failure.scenario,
            scenario_name: failure.scenario_name,
            seed: failure.seed,
            include_patches: includePatches,
            request: cloneRequest(failure.request_snapshot),
            reason: failure.errors.length > 0
                ? failure.errors.join(' | ')
                : (failure.deterministic ? '约束校验失败' : '确定性失败')
        }));

        return {
            total,
            pass,
            fail,
            pass_rate: total > 0 ? Number((pass / total).toFixed(4)) : 0,
            deterministic_rate: total > 0 ? Number((deterministicPass / total).toFixed(4)) : 0,
            patch_rate: includePatches ? (total > 0 ? Number((patchPass / total).toFixed(4)) : 0) : null,
            include_patches: includePatches,
            scenario_count: scenarios.length,
            random_scenario_count: randomScenarios.length,
            failures: limitedFailures,
            replay_cases: replayCases,
            scenario_breakdown: scenarioBreakdown
        };
    }

    const api = {
        version: VERSION,
        SeededRng,
        LocalMapGenerator,
        buildMapSpecFromQuestRequest,
        createScenarioLibrary,
        createRandomizedScenarioBatch,
        createSimulatedLLMPatches,
        applyPatchesWithValidation,
        runReliabilitySuite,
        collectCapabilityCoverage,
        cloneMap,
        cloneRequest
    };

    global.LocalMapAlgo = api;
}(window));
