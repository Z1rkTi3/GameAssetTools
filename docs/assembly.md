# Контракты модульной сборки

`game_asset_tools.assembly.contracts` проверяет описания деталей, постоянного
рига и слота до изменения Blender-сцены. `assembly.inspection` дополнительно
сверяет реальные rest-кости, жёсткие привязки и маркеры соединений/контактов.
`assembly.library` публикует независимые детали, а `assembly.replacement`
заменяет один зарегистрированный компонент внутри существующей Blender-сборки.
`assembly.authoring` объединяет регистрацию, проверку, публикацию и установку
в общий workflow Blender UI и Python. Интерфейсы сохраняются в component record
в той же транзакции, что и замена, и переживают Save/Open. Описание UI — в
[руководстве аддона](blender_addon.md#библиотека-модульных-компонентов).
Анализ столкновений/походки и проектный импорт Godot остаются отдельными задачами.
Эти проверки не означают готовность всей модели к игре.

## Постоянные компоненты рецепта

`ComponentSpec("Rig", persistent=True)` создаёт компонент при первой сборке,
затем сохраняет его при смене стадии, версии рецепта и пересборке зависимой
геометрии. Это подходит для редактируемого скелета с авторскими Actions.
Явный запрос пересоздать существующий постоянный компонент отклоняется.
Изменение конфигурации, затрагивающее его, удаление объявления или снятие
`persistent=True` новым рецептом требуют явной миграции. Сохранённый lifetime
нельзя обойти через `replace_edited`: он защищает в том числе rest-позу и Actions,
которые не входят в обычный fingerprint меша. Флаг не заменяет
контракт совместимости костей/сокетов и не задаёт кинематику автоматически.

Превращение уже существующего mutable-компонента в persistent тоже требует
миграции: одного нового spec недостаточно для изменения сохранённого контракта.
Первичная сборка и добавление нового постоянного компонента остаются разрешены.

Постоянный компонент не может зависеть от автоматически заменяемого соседа:
такой план отклоняется до изменения сцены. Геометрия может зависеть от Rig;
обратная связь должна выражаться интерфейсом соединения, а не циклом recipe.
При отказе сборки Core освобождает новые неиспользуемые Actions, включая
fake-user клипы, сохраняя прежние пользовательские анимации. Регрессия:

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/blender_rig_rollback_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_persistent_components_test.py
```

Вторая проверка использует настоящий риг с ручными rest/Action-правками: обычные
geometry/stage/version/style rebuild сохраняют их, а опасные планы отклоняются
до изменения ID и metadata. Общий `tests/run_blender_tests.py` не обнаруживает
standalone suites автоматически, поэтому эти команды запускаются отдельно.
Изменение исходников и создание ZIP не обновляют установленный пакет.

## Формат 1

Все структуры — immutable dataclasses; читать JSON следует через
`read_contract(path, "rig" | "part" | "slot")`. Для уже прочитанного словаря
есть `rig_from_dict`, `part_from_dict`, `slot_from_dict`. `dataclasses.asdict`
даёт структуру для `json.dumps`. Неизвестные/пропущенные поля, повторные ID,
повторные JSON-ключи, NaN/Infinity и boolean вместо версии/числа отклоняются.

| Тип | Поля |
| --- | --- |
| `RigContract` | `schema_version`, `id`, `revision`, `coordinates`, `bones`, `joints` |
| `PartContract` | `schema_version`, библиотечные `id`/`revision`, `rig_id`/`rig_revision`, `coordinates`, `input`, `outputs`, `bones`, `bindings`, `contacts`, `joints` |
| `SlotContract` | `schema_version`, `slot_id`, `rig_id`/`rig_revision`, `input`, `outputs`, `binding_bones`, `contacts`, `joints` |
| `Coordinates` | `units="m"`, `up`, `forward`; разные оси из `+X/-X/+Y/-Y/+Z/-Z` |
| `Frame` | `origin[3]`, `basis[3][3]`: строки матрицы, без scale/shear/mirror |
| `Bone` | `id`, `parent` (ID или null), `rest: Frame` |
| `Port` | `id`, `interface`, `bone`, `frame: Frame` |
| `RigidBinding` | стабильный локальный `object_id`, `bone`, `bind_frame: Frame` |
| `SoleContact` | `id`, `bone`, `position[3]` |
| `JointLimit` | `bone`, единичная `axis[3]`, `lower`, `upper` |

`PartContract.id` обозначает библиотечную деталь. `SlotContract.slot_id`
обозначает место в конкретной сборке. Они не сравниваются: стандартная и
бронированная стопы могут подходить к одному слоту. ID объектов локальны детали;
текущий API замены получает отдельно `asset_id` и ключ `component`. Вызывающий
код явно выбирает соответствие компонента слоту; `slot_id` не используется
для поиска объектов по похожему имени.

Все `rest` и port `frame` выражены в **пространстве рига в исходной позе**.
Это позволяет сравнивать положение и оси соединения без вычисления текущей
анимационной позы. `bind_frame` выражен в пространстве кости и определяет
положение origin жёстко связанного объекта. Контакт подошвы также выражен в
пространстве своей кости. `axis` шарнира — локальная ось кости; пределы заданы
в радианах относительно rest pose, обязаны включать ноль.

Basis должна быть правой ортонормальной матрицей с determinant=1. Допуск —
`1e-5` для координат в метрах и компонент basis/оси; скрытого нормализования,
перемасштабирования или отражения нет. Конверсия Blender/Godot должна быть
явной и применяться ко всем связанным frame; простая смена `up` не является
конверсией. В текущем walker source: Blender +Z вверх, -Y вперёд, кости вдоль +Y.

У полного рига один корень, все родители существуют, циклы запрещены. Деталь
может хранить только используемый поднабор костей; внешний родитель проверяется
при сравнении с полным ригом. Для каждого порта, binding, контакта и шарнира
детали обязательно описание rest соответствующей кости.

## Проверка кандидата

```python
from game_asset_tools.assembly.contracts import read_contract, check_compatibility

rig = read_contract("industrial_biped.rig.json", "rig")
slot = read_contract("left_foot.slot.json", "slot")
part = read_contract("armored_foot.part.json", "part")
issues = check_compatibility(part, slot, rig)
for issue in issues:
    print(issue.component, issue.field, issue.message, issue.remedy)
```

Проверяются семейство и revision рига, координаты, rest и родители костей,
входной интерфейс/pivot/basis, набор костей жёстких привязок, все выходные
соединения сохраняемых соседей, контакты подошвы, оси и необходимые диапазоны
шарниров. Дополнительная геометрия с уникальным `object_id` допустима; её
binding может иметь иной `bind_frame`. Это описание формы кандидата, а не
основание двигать соседние части. Выходы, не используемые данным слотом,
допустимы; потребитель обязан подключать только явно объявленные соединения.

Требования шарниров берутся из постоянного рига также для костей входных и
выходных портов кандидата/слота. Поэтому колено, чей неподвижный кожух связан
с `Knee`, обязано объявить ось и диапазон подвижного выхода `LowerLeg`.
Удаление `joints` одновременно из детали и слота не обходит эту проверку.

Меньший диапазон шарнира отклоняется. Более широкий допустим при той же оси:
анимация по-прежнему ограничивается контрактом рига/слота. Изменённая ось или
размер соединения требуют явного адаптера/другого семейства; текущая проверка
ничего не исправляет автоматически. Пара `interface/bone` входа значима, его
локальное имя `id` не обязано совпадать с именем входа слота; выходы сравниваются
по стабильным ID.

Несовместимость возвращает tuple `Issue`: `severity`, `code`, `component`
(slot ID), `field`, `expected`, `actual`, `message`, `remedy`. Сейчас все
найденные несоответствия контракта — `error`; предупреждения о художественных
или намеренных пересечениях относятся к будущей геометрической диагностике.
Повреждённая структура вызывает `ContractError` с тем же `.issue`.

## Проверки и границы

Из корня исходников:

```powershell
python -m unittest discover -s tests -p "test_assembly_contracts.py"
python -m unittest discover -s tests -p "test_*.py"
```

Fixtures в `tests/test_assembly_contracts.py` воспроизводят 16 rest-позиций
из `MechBattler2/art/walkers/finish_walkers.py:armature()` и размеры GroundShoe
из `walker_recipe.py`. Они независимы от расположения игры на диске. Ось X
взята из существующей `pose_leg`; численные joint limits в тестах являются
контрольными требованиями теста, а не утверждёнными пределами игрового рига.

Есть положительные сравнения описаний стопы/колена/корпуса и адресные отказы при изменении
подошвы, оси/предела колена, hip/output socket, rest/parent, привязки к другой
ноге, системы координат и повреждении JSON. Эти чистые проверки не измеряют
меши, веса, normals, foot skid, столкновения или Actions.

## Read-only сверка в Blender

`inspect_rig` проверяет полный состав костей, родителей и `Bone.matrix_local`
существующего armature. `inspect_part` дополнительно проверяет меши и Empty
по явным mappings. Ссылка `ObjectRef(component, local_name)` разрешается только
по существующим `gat_asset_id/gat_component/gat_local_name/gat_generated` внутри
asset root. Переименование Blender-объектов не меняет идентичность.

```python
from game_asset_tools.assembly.inspection import ObjectRef, inspect_part

report = inspect_part(
    "assembly_fixture", "Foot", part, rig,
    armature=ObjectRef("Rig", "Skeleton"),
    objects={"shoe": ObjectRef("Foot", "Shoe")},
    sockets={"ankle": ObjectRef("Foot", "AnkleSocket"),
             "service": ObjectRef("Foot", "ServiceSocket")},
    contacts={"heel": ObjectRef("Foot", "HeelContact"),
              "toe": ObjectRef("Foot", "ToeContact")},
)
```

Ключи `objects` — `RigidBinding.object_id`; ключи `sockets` — IDs входа и всех
выходов; ключи `contacts` — IDs контактов. Все принадлежащие компоненту объекты
обязаны попасть в mappings. Неоднозначные, чужие, пропущенные и повторные ссылки
отклоняются. Объекты, одновременно включённые во внешнюю коллекцию, и linked
library data получают ошибку ownership для последующей безопасной замены.

Поддержаны два способа жёсткой привязки: один Armature modifier с единственным
единичным vertex weight нужной кости либо прямой bone parent без skin modifier.
Смешивать эти способы на одном объекте нельзя. Проверяются `bind_frame`,
полнота/конечность геометрии и weights, applied scale=1, отсутствие shear/mirror,
единица Blender-сцены в метрах, включённый skin без envelopes/mask.
Для skin кость обязана иметь `use_deform=True` и один B-Bone segment: иначе
она либо не двигает mesh, либо может гнуть жёсткую деталь. При bone parenting
`use_deform` не влияет на движение и не является причиной отказа.

Socket — owned Empty с `gat_socket=port.id` и bone parent указанной кости.
Контакт — owned Empty с `gat_contact=contact.id` и таким же bone parent.
Проверяются действительные rest transforms сокетов и позиции контактных маркеров.
Это ещё не геометрическое доказательство, что marker лежит на подошве меша:
такую проверку нужно выполнять совместно с контрольными позами/поверхностью.

Текущие frame/subframe, Actions, pose transforms, selection и active object не
переключаются. Для bone-parent объекта rest восстанавливается из его evaluated
world matrix, текущей pose matrix кости и её rest matrix. Перенос/поворот корня
и armature допустимы. Дополнительная промежуточная иерархия, собственные
object constraints/animation, shape keys и дополнительные mesh modifiers пока
возвращают конкретную ошибку неподдерживаемого случая: они не получают ложный
`pass`. Исходник не запекается и не исправляется инспектором.

Результат — JSON-совместимый словарь с `status`, `scope`, `read_only`, `checked`
и массивом `issues` прежнего формата. `scope=ownership_rest_rigid_binding_markers`
ограничивает утверждение результата. Проверка численных пределов Blender
constraints, normals, intersections, animation quality и экспорт в этот scope
не входят. Проверку совместимости кандидата с целевым SlotContract нужно также
выполнить отдельно.

Реальный тест из исходного checkout:

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/blender_assembly_inspection_test.py
```

Он создаёт собственную fixture `tests/fixtures/assembly_inspection` во временном
проекте, не открывая пользовательские `.blend`. Проверяет согнутую pose и кадры
1, 12, 7.375, отдельный случай rest basis с вращением по трём осям;
сравнивает geometry/ownership/rig/Actions/frame/selection до и после
инспекции и SHA256 временного сохранённого `.blend`. Отчёт с абсолютным checkout,
версией Blender и source hashes: `output/assembly_inspection/report.json`.
Поле `suite` хранит число выполненных тестов и фактический итог последнего запуска.
Инспекция сама замен не выполняет; staging/rollback и сохранение соседей,
рига и клипов относятся к отдельной операции `replace_part` ниже.

## Независимая библиотека

Библиотечная revision публикуется как `<root>/<part.id>/<revision>/` с двумя
файлами: `manifest.json` и `payload.blend`. Manifest содержит отдельную версию
формата библиотеки, полный PartContract, SHA256 payload и явные IDs объектов по
ролям mesh/socket/contact. Существующая revision никогда не перезаписывается;
публикация временного каталога происходит только после повторного чтения и
проверки payload. Нельзя подменить revision путём `..`, абсолютным путём или
символической ссылкой внутри библиотеки.

Источник сначала проходит `inspect_part`. Для payload создаются новые mesh и
Empty без parents, modifiers, vertex groups, ownership сборки и Actions. Их
трансформации заданы в каноническом rig-rest пространстве manifest; геометрия
остаётся локальной относительно origin объекта. Armature и соседние компоненты
не сохраняются. Текущая pose/frame источника не переключается. Будущий binder
сможет восстановить привязку по bone ID и `bone.rest @ bind_frame`; это не
скрытое изменение размеров или автоподгонка к несовместимому ригу.

Чтение сначала проверяет JSON, пути и hash, затем загружает из `.blend` только
detached коллекцию и проверяет реальные объекты, геометрию и rest transforms.
Контекст чтения владеет исключительно созданными им datablocks и очищает их
при успехе и отказе. Библиотечное чтение не подключает детали к пользовательской
сборке и не является транзакцией замены. Практические тесты используют временные
публикации и независимые тестовые сборки, не пользовательские `.blend`.

### Python API и время жизни данных

```python
from game_asset_tools.assembly.library import publish_part, read_part, open_part

entry = publish_part(
    library_root, asset_id, component, part, rig,
    armature=armature_ref, objects=object_refs,
    sockets=socket_refs, contacts=contact_refs,
)
entry = read_part(library_root, part.id, part.revision)
with open_part(library_root, part.id, part.revision) as payload:
    mesh = payload.objects["shoe"]
    rest_in_rig = mesh.matrix_basis.copy()
    # payload.sockets / payload.contacts: явные локальные IDs -> Empty.
    # Данные не linked в scene; caller не должен сохранять ссылки после with.
```

`read_part` проверяет только manifest и SHA256, без импорта `bpy`. Это не pass
Blender-структуры. `open_part` повторно проверяет hash приватной временной копии
файла и читает именно её: замена файла между проверкой и load не подменяет
payload. Деталь возвращается как `PartPayload(entry, collection, objects,
sockets, contacts)`. Состав `.blend` и все загруженные datablocks проверяются:
armature/Actions/сцены/тексты, лишние объекты, скрытые ID properties, повреждённые
rest transforms и внешние зависимости отклоняются. Имена Blender могут менять
суффикс `.001`; идентичность берётся только из проверенных role/ID tags.

У detached объектов сохранённый rig-rest transform находится в `matrix_basis`:
`matrix_world` ещё не вычислена depsgraph. При привязке skin-объекта к
целевому armature world будет `target_rig.matrix_world @ bone.rest @ bind_frame`.
Для bone parent применяется текущая `pose_bone.matrix @ bind_frame` и корректный
parent inverse. Чтение библиотеки само не подключает данные к сцене. Постоянную
привязку и ownership экземпляра выполняет описанный ниже `replace_part`;
сохранение рабочего `.blend` остаётся отдельным действием вызывающего кода.

`open_part` фиксирует созданные ID **до** передачи управления caller. Поэтому
новые собственные данные caller не удаляются после `with`; любые сохранённые
копии должны владеть также копиями mesh/material/node-tree/image зависимостей.
Временные IDs самого payload после `with` недействительны. API используется
staging-биндером замены и не является командой постоянного append в рабочую сборку.

`LibraryError.issues` содержит те же адресные `Issue`, что инспекция; malformed
вложенный PartContract может вернуть `ContractError.issue`. `revision_exists`
означает необходимость новой revision. Публикация использует no-replace rename
в пределах одного volume, включая уже существующий пустой каталог. Проверено
на Windows. Linux использует `renameat2(RENAME_NOREPLACE)`; его выполнение здесь
не проверялось. Если платформа не предоставляет поддержанный primitive, публикация
отклоняется; существующая revision не заменяется небезопасным fallback.

### Материалы и границы формата

Сохраняются локальная геометрия, UV, пользовательские normals, индексы материалов
граней, эффективные DATA/OBJECT material slots и `gat_material_role`. Shader
graphs и вложенные shader groups копируются. Неподвижные FILE/GENERATED images
упаковываются в копиях с пустым внешним filepath; исходный image не pack/reload.
Чтение после удаления исходного PNG проверено на настоящем `.blend` и пикселях.
`Image.copy()` не сохраняет текущий ImBuf в Blender 5.2, а `FILE.pack()` может
упаковать прежний файл вместо несохранённой правки. Для GENERATED и dirty FILE
пиксели переносятся в буфер копии и упаковываются через GENERATED; исходный image
не pack/update/reload. Размер и float precision сохраняются. Регрессия сравнивает
пиксели повторно открытого payload, dirty flags, packed bytes и файл исходника.
Scene Object/Collection pointers, OSL/IES, анимированные shader graphs, movie/UDIM,
linked данные и произвольные вложенные metadata не считаются переносимыми.

Поддержана уже проверенная жёсткая геометрия без shape keys и дополнительных
mesh modifiers. Bevel/Weighted Normal и другие modifiers сейчас получают отказ
`unevaluated_modifiers`. Это не blocker текущего `art/walkers/walker_recipe.py`:
его `hull()` строит фаски непосредственно геометрией, а `finish_walkers.py`
добавляет только Armature modifier. Живые Bevel/WeightedNormal в этих recipes
не обнаружены; пользовательские `output/blend` ради этой проверки не открывались.
Явное запекание дополнительных modifiers потребуется при появлении реального
редактируемого источника с ними; общий API под одну новую fixture не добавляется.
Контакт остаётся marker-vs-manifest, без проверки фактической подошвы/походки.
Публикация/чтение не добавляют UI/CLI, установку аддона или Godot import.

### Практические проверки

```powershell
python -m unittest discover -s tests -p "test_assembly_library.py"
blender --background --factory-startup --python-exit-code 1 --python tests/blender_assembly_library_test.py
```

Blender suite создаёт GAT fixture во временном каталоге. Проверены skin и bone
parent, повёрнутая rest basis и текущая согнутая поза, окраска/UV/custom normals,
полное удаление source-сцены и чтение в две свежие анимированные сборки с разными
mesh/material datablocks. Snapshot охватывает frame, selection, mesh, rig,
Actions и ownership; SHA256 временного сохранённого source `.blend` не меняется.
Проверены отказы до/после записи, отсутствие staging-мусора, unchanged существующая
revision, malformed `.blend`, подмена файла, Action/дубли IDs/неверный socket/
скрытые metadata, внешний IES и modifier. Hash, строгие пути/JSON/версии и
no-overwrite покрыты отдельными Python tests. Фактический итог и source hashes:
`output/assembly_library/report.json`; полный успех записывается только после
завершения всего Blender suite.

## Адресная замена в существующей сборке

Операция доступна в исходном Core как Blender Python API:

```python
from game_asset_tools.assembly.inspection import ObjectRef
from game_asset_tools.assembly.replacement import replace_part

report = replace_part(
    library_root, asset_id, component,
    current_part, slot, rig_contract,
    candidate_id, candidate_revision,
    armature=ObjectRef("Rig", "Skeleton"),
    objects=mesh_mapping,
    sockets=socket_mapping,
    contacts=contact_mapping,
    dry_run=True,
)
```

`current_part`, `slot` и `rig_contract` — проверяемые dataclass-контракты.
Словари `objects`, `sockets`, `contacts` задают **все** прежние объекты компонента
через `ObjectRef(component, local_name)`, как при публикации. Название armature
в примере относится к fixture; приложение обязано передать собственный стабильный
ключ. Режим Blender должен быть OBJECT. `persistent=True`, approved/locked,
непринятые ручные правки, внешние пользователи старых объектов и неоднозначные
коллекции приводят к отказу. Принятие авторских правок и снятие защиты выполняются
отдельно; `replace_part` не предоставляет флаг обхода этой защиты.

`dry_run=True` проверяет текущую сборку, совместимость кандидата и реальные
данные его `.blend`, возвращая `status="planned"` без установки. Обычный вызов
повторяет проверки, создаёт собственные копии геометрии, материалов, shader groups
и изображений, привязывает их к **существующему** armature и выполняет инспекцию
до удаления старых объектов. Rig, его datablock, Actions и текущий кадр
не пересоздаются. Матрица detached payload читается из `matrix_basis`;
bone-parent markers учитывают rest-ориентацию и смещение до хвоста кости.

Успешный отчёт имеет `status="replaced"`, `part`, `payload_sha256`, число старых
и новых объектов и словарь `mappings` с разделами `objects`, `sockets`, `contacts`.
Значения каждого раздела — сериализованные `ObjectRef`. Для следующей инспекции
или замены следует принять **новый** `part` и mappings; прежние Blender IDs
после успеха удалены. Ключ компонента сохраняется. Выделение и активный объект
переносятся по семантической паре role/ID; если прежний ID отсутствует у кандидата,
используется существующий rig.

Компонент записывает `library_part` с ID/revision/hash и идентификатором экземпляра.
Его нельзя незаметно перегенерировать из процедурного recipe: такой build-план
будет заблокирован. Это относится и к общему переходу стадии/версии, если он
выбирает библиотечный компонент. Повторный `replace_part` разрешён с новыми mappings.
Автоматическая перепривязка дочерних объектов, constraints, drivers и произвольных
ID-ссылок не выполняется: ссылки на удаляемые объекты сначала требуют явного
решения. Совпадение выходных портов в контракте само по себе не переподключает
объекты соседнего компонента.

При отказе проверок, создания копий, postflight или восстановления выделения
до commit возвращаются прежние objects/collections, records и выделение;
временные данные удаляются. Новые fingerprints вычисляются до commit.
Копии material/node-group/image зависимостей принадлежат экземпляру: при следующей
замене освобождаются только его неиспользуемые данные. Используемые другим объектом
зависимости и посторонние авторские orphan IDs сохраняются; общий orphan purge
не вызывается. Операция не записывает файл, не меняет опубликованную revision
и не заменяет пользовательский Undo после успешного commit.

Результат проверяет структуру привязки и неизменность контрактов. Он не доказывает
отсутствие столкновений, красивую походку, соответствие подошвы контактным markers
или готовность материала к игровому рендеру. Это отдельные проверки фактической
геометрии/анимации и экспортированного результата.

Команда регрессии:

```powershell
blender --background --factory-startup --python-exit-code 1 --python tests/blender_assembly_replacement_test.py
```

Suite содержит обычную и повторную замену, dry run, защиту ручных правок,
несовместимость, повреждённый payload, внешние constraints/drivers/ID/RNA-ссылки,
искусственные отказы до commit, повёрнутые rest/bind и скрытую коллекцию назначения.
Проверяется также повторное использование материалов без накопления копий
и сохранение shader graph, используемого сторонним объектом. Фактический итог
последнего запуска, версия Blender и SHA256 исходников записываются в
`output/assembly_replacement/report.json`; наличие теста не означает его успешный
запуск на текущей версии файлов. Blender UI использует `assembly.authoring`;
отдельная CLI-команда библиотеки не добавлена. Установленная копия аддона
не обновляется при изменении исходников или создании ZIP.

## Отдельный pilot: настоящая левая стопа player

Этот раздел сохраняет историю раннего внешнего эксперимента с прежним layout,
а не инструкцию для текущих игровых source16. Его локальные драйверы не входят
в общий набор поставки Core; самостоятельные проверки используют включённые
`tests/fixtures` и не требуют Mech Battler на диске.

Первоначальный walker pilot проверяет независимую публикацию геометрии стопы.
Его отдельный ignored output содержит копии recipe/config/style/finisher
с SHA256 источников; этот снимок не следует считать актуальной игровой моделью.
Обычный GAT build создаёт DETAIL player в factory-сцене. Из копии finisher
используются только `armature()` и `animate()` для полного 16-bone rig и прежних
шести клипов; `main()`, `merged_mesh()`, atlas и export не запускаются.

Точный состав стопы задан stable local names: `LeftLeg/GroundShoe`, `ToeArmour`,
`HeelSpur`, `FootStrikePlate`. На **новой pilot-копии** эти четыре объекта получают
отдельный ownership компонента стопы; вся остальная геометрия сохраняется.
Жёсткая bone binding берётся из авторской метки `walker_bone`, без угадывания
по Blender name. Входной ankle marker принадлежит `LeftFoot`. Два контакта
описывают середины нижних рёбер GroundShoe 0–1 и 4–5 с проверкой положения на
реальной нижней плоскости: размеры от прямоугольного bounding box не учитывают
фаску и не должны подменять поверхность подошвы.

После подготовки сохраняется отдельный source `.blend`. Дальше уже существующие
инспекция/публикация должны сохранить IDs соседей, rig, clips, frame и SHA256
этого source; чтение после factory reset должно загрузить только meshes стопы
и её markers. Это pilot новой authoring-копии, не миграция пользовательских
`output/blend`; он не вызывает новый API замены и не проверяет интеграцию этого API
с текущими walker-файлами. Источник pilot также не объявляет точные
mechanical joint limits; они не выдумываются ради pass. Используются авторские
GAT material roles, без заявления о готовности игрового cel-атласа.
