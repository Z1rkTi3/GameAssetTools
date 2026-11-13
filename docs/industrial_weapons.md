# Сменные промышленные weapon payload

`industrial_cannon` и `industrial_emitter` — два самостоятельных BLOCKOUT-рецепта
категории `weapons` существующего GameAssetTools. Они дают реальные полые/сплошные
сетки и жёсткий skin, а не только именованные sockets. Художественная доводка,
новый баланс оружия и изменение production-моделей Mech Battler в этот этап
не входят. Прежний static `industrial_walker` и его defaults не изменены.

## Неизменяемый Rig и сменная геометрия

Оба рецепта создают persistent-компонент `Rig` и зависимый `WeaponPayload`.
Профиль `game_assets/weapons/industrial_biped.rig.json` содержит 16 костей
семейства `industrial_biped`, revision 1: rest/parents соответствуют исходному
Game `art/walkers/walker_rig.py:bone_definitions()`. `joints` пуст: пределы
физических суставов здесь не придуманы. Единицы — метры, вверх `+Z`, вперёд `-Y`.

Изменение длины, поперечника или борта пересобирает только `WeaponPayload`.
Rig, пользовательские Actions и соседние ассеты сохраняются. Оба борта есть
в одном фиксированном риге; `payload.side` выбирает binding bone и расположение
геометрии. Отрицательный scale и автоматическое отражение несовместимой детали
при установке не используются. Right payload требует right Slot; left требует left.

Параметры находятся в обычном `config.json`, Geometry controls и CLI `--set`:

| Параметр | Назначение |
| --- | --- |
| `payload.side` | `left` или `right`; параметр геометрии, а не миграция Rig |
| `payload.length` | Длина ствола / излучателя, 0.25–1.5 м |
| `receiver.width` | Ширина корпуса, 0.30–0.60 м |
| `receiver.height` | Высота корпуса, 0.28–0.55 м |

Оба metadata объявляют `source_files` для общего helper и JSON-профиля.
Их изменение учитывается в lifecycle и revision Geometry draft; wrappers
импортируют helper по hash его содержимого и профиля. Изменять или удалять
persistent rest-профиль существующего blend без отдельной миграции нельзя.

## Посадка и направление дула

IN `payload`, interface `walker_weapon_payload_v1`, стоит в rest-frame
`WeaponMountLeft/Right`: origin `(-1.13,-0.1,2.5)` или `(1.13,-0.1,2.5)` и identity
basis. Это тот же frame, который объявляет Game `PayloadSocket`; нельзя переносить
IN на видимый торец втулки, сохраняя прежнюю версию интерфейса.

Механическое соединение — female-втулка вокруг существующего male:

| Величина | Значение |
| --- | --- |
| Центр относительно IN | `X = side × 0.215 м`, `Y=Z=0` |
| Male envelope radius / depth | `0.09 / 0.035 м` |
| Female inner apothem | `0.092 м`: радиальный зазор до envelope 2 мм |
| Female outer radius / depth | `0.13 / 0.041 м`: осевой зазор по 3 мм |
| Сечение втулки | 12 граней, сквозная полость и торцевые кольца |

Внутренний circumradius вычисляется из apothem: зазор сохраняется на плоских
гранях, а не только на вершинах. `_measure` проверяет настоящую сетку connector.
Это один фиксированный mating shape; прочность, износ, FEA, столкновения и
совместимость со всеми сторонними креплениями не сертифицируются.

OUT `muzzle`, interface `walker_weapon_muzzle_v1`, лежит на оси реального
переднего торца. Его basis identity, направление выстрела берётся из
`part.coordinates.forward == '-Y'`, а не из local Z маркера. Длина меняет OUT,
но не IN. У Slot нет обязательных outputs: muzzle принадлежит заменяемой детали
и не является соседом, который нужно удерживать на прежнем месте.

## Сборка, библиотека и доставка

1. Выбрать рецепт в существующей категории Weapons и выполнить Build BLOCKOUT.
2. В Recipe Authoring выполнить «Проверить и зарегистрировать IN/OUT».
   Hook `authoring_tools()/run_authoring_tool()` измеряет объекты и вызывает
   существующий `assembly.authoring.register_document` без изменения fingerprints.
3. В Component Library выбрать `WeaponPayload`, указать явную папку библиотеки,
   стабильный part ID и revision, затем Validate и Publish.
4. Для другого совместимого payload использовать Plan/Install той же библиотеки.
   Сохранить blend после установки. Locks, approval, ручные правки, внешний
   пользователь компонента и несовместимый борт блокируют замену.

Тот же workflow доступен Python API; новых library CLI-команд не добавлено:

```python
entry = Registry(project_root).get("industrial_cannon")
config = load_config(entry)
build(entry, config, load_style(project_root))
recipe = entry.load()
recipe.run_authoring_tool(entry.id, "register_interface")
publish_component(library, entry.id, "WeaponPayload", "cannon_payload", 1)
# Другой donor предварительно собирают/регистрируют/публикуют тем же способом.
install_component(library, entry.id, "WeaponPayload", "emitter_payload", 1)
result = export_asset(entry.id, output, entry=entry, overwrite=False)
manifest = recipe.delivery_manifest(entry.id, result["glb"])
```

`recipe.describe(asset_id)` возвращает `(Part, Slot, Rig, mappings)` с настоящими
`ObjectRef`. После Library install он читает сохранённый установленный интерфейс,
включая donor mesh IDs и перемещённый muzzle. Сохранённый recipe config не выдаётся
за конфигурацию donor: геометрия библиотеки заменяется через её revision.

`export_context` допускает только статический rest-export. Он временно ставит
Rig в REST и включает два declared delivery sockets, даже если Library хранит
их как helpers. В `finally` восстанавливаются прежние pose_position/helper flags;
Actions, ключи, текущая поза и frame не перезаписываются. `animations=True`
отклоняется до создания доставки. Передавайте `entry` в `export_asset`, иначе
Core не может обнаружить recipe hook.

`delivery_manifest(asset_id, glb_path)` читает настоящий GLB, сверяет точные
node names/weighted skin и возвращает JSON-safe документ:

```text
schema_version: 1
kind: weapon_payload
asset: текущий ID сборки
component: WeaponPayload
glb_sha256
part: полный PartContract
rig: полный RigContract
nodes: {armature, input, muzzle, meshes: {stable mesh ID: exact GLB node name}}
heat_nodes: [stable mesh IDs]
material_roles: {stable mesh ID: roleName}
connector: измерительный стандарт посадки
```

`asset` содержит ID текущей сборки, не строку `WeaponPayload`.
`heat_nodes` исключает Connector. Роли — `Painted_Metal`, `Metal_Silver`, `Rubber`,
`Metal_Bronze`, `Glass_Clear`; это авторские семантические роли, не готовые
Godot shader resources. Game adapter явно сопоставляет их материалам и
преобразует Blender `-Y` в Godot forward. SHA привязывает manifest к конкретному
файлу. Документ не подтверждает импорт/aim/heat в Game: для этого нужны его
отдельные adapter/runtime-проверки.

## Проверка

Обычный Python без bpy:

```text
python -m unittest discover -s tests -p test_recipe_sources.py
python -m unittest discover -s tests -p test_industrial_weapons.py
```

Настоящий Blender:

```text
blender --background --factory-startup --python-exit-code 1 --python tests/blender_industrial_weapons_test.py
```

Тесты используют временные копии recipes, реальные meshes/skin, UI register/publish,
A→B→A replacement, Rig/Actions/user content, Save/Open, оба борта, длину/muzzle,
защиты, rest export и finally при ошибке. UI draft и lifecycle проверяются
изменением только helper во временном проекте. Отдельная UI-регрессия переключает
категорию weapons с numeric index 4 на 0 между проектами и обратно, сохраняя
независимые несохранённые drafts и читая реальные RNA getters. Счётчик callback
также проверяет отсутствие промежуточного stage RNA read при ещё невалидном
category index: draft использует исходный stage ID из session.
Машинный отчёт по умолчанию —
`output/industrial_weapons/report.json`; `INDUSTRIAL_WEAPONS_OUTPUT` задаёт другое
место. Он содержит абсолютный root и SHA проверявшихся исходников.

Ожидаемый negative stderr: `test_sidebar_registers_real_interface_and_library_publishes`
вызывает настоящий оператор с запрещённым tool ID. Blender печатает
`Error: Unknown authoring tool for the selected recipe`; тест требует именно
этот RuntimeError через `assertRaisesRegex`. Это проверка whitelist, не ошибка
обычного UI workflow. RNA category warnings не являются ожидаемым результатом.

Наличие тестов не означает их успешный запуск: фактические команды, версии и
результаты следует брать из отчёта текущей проверки.

## Воспроизводимая доставка четырёх вариантов

Из корня исходного проекта запустить отдельный Blender-процесс:

```text
blender --background --factory-startup --python-exit-code 1 --python scripts/export_industrial_weapons.py -- --project=. --output=output/industrial_weapons_delivery_01
```

`--project` выбирает исходный Core и recipes; абсолютные машинные пути в driver
не зашиты. `--output` обязан указывать на новую папку, даже существующая пустая
папка отклоняется. Нужна несохранённая factory-сцена с Cube/Camera/Light без GAT
assets. Driver не открывает `.blend`, не выполняет factory reset и не удаляет
исходные объекты; другой загруженный Core или населённая сцена вызывают отказ.

Для `industrial_cannon` и `industrial_emitter` строится BLOCKOUT слева, затем
обычный Rebuild того же asset справа с сохранением persistent Rig. Каждый вариант
регистрирует измеренные IN/OUT и получает файлы:

```text
<output>/<kind>/<side>/glb/<kind>.glb
<output>/<kind>/<side>/glb/<kind>.weapon.json
<output>/<kind>/<side>/blend/<kind>.blend
```

`side` — `left/right`. JSON формируется штатным `delivery_manifest` после реальных
save/export; его schema не меняется. Экспорт отбирает только owned objects текущего
asset. `.blend` сохраняет всю новую рабочую сцену, включая default-объекты и уже
созданный соседний asset. Успешный `index.json` появляется после всех четырёх
доставок и содержит конфигурации, относительные пути, SHA и версии. При ошибке
новая папка может содержать частичные результаты; повторный запуск использует
другой путь. Команда создаёт доставку, а не подменяет отдельные тесты Blender/Godot.
