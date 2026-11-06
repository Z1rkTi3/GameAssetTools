# Save and export

For transparent toon/standard PNG frames, atlases and shared Blender/Codex render
settings, see [sprite export](sprites.md). The `sprites` operation is separate
from GLB export and does not modify source materials.

`save` writes the current Blender scene to `output/blend/<asset>.blend`. It preserves
other user scene content, including manual edits. The headless build/rebuild/status/
delete commands save automatically; the add-on saves only on request.

Use `save <asset> --view-copy --save-view front` (or `--save-view perspective`) for a separate
`output/blend/<asset>_view.blend` prepared for opening in Blender. The copy frames
the full evaluated asset, including modifiers and parent transforms, in every
saved 3D viewport and enables material preview. Other standard preview directions
are accepted too. The working file, viewport state, and selection are retained,
including if saving fails. This uses Blender's save-copy API, without UI control
or preference changes. The scene must contain a saved 3D viewport. `--overwrite`
can replace an existing viewing copy, but can never replace the currently open
source file through this mode; choose another output directory in that case.

Validation output has explicit modes: `validate <asset> --report-mode stdout`
returns JSON without writing a report; `unique` creates an exclusive UUID-named
report; `replace` updates only `reports/<asset>_validation.json`. These modes allow
repeat checks without `--overwrite` and grant no overwrite permission for blend,
preview, or GLB artifacts. The default `file` mode retains the existing fixed path
and explicit overwrite requirement. `validate --dry-run` still validates without
writing a file, regardless of report mode.

`export` validates then writes `output/glb/<asset>.glb`. It selects generated asset
objects and its root, omits construction helpers and unrelated/unmanaged objects,
applies modifiers through the glTF exporter, and includes custom properties. Named
socket empties can be registered as non-helper objects and retained. Animation is
disabled by default; the optional skeletal path is described below.

Recipe coordinates use +Z up and -Y front in meters by default. The glTF exporter
converts to glTF +Y up; Blender -Y front maps to glTF +Z. Godot imports the GLB basis;
gameplay code using Godot -Z forward may rotate the visual root 180 degrees or
choose its model-front convention accordingly. Do not rotate individual meshes
ad hoc. Root scale and hierarchy are retained. Blender's display unit scale is
temporarily normalized during export and restored afterward.

Existing output needs `--overwrite`, independent of permission to rebuild generated
geometry. The exporter restores selection, active object, and object visibility.
GLB verification checks magic/version/length, JSON structure, meshes, materials,
and nodes. The smoke suite additionally imports each GLB into a fresh Blender scene.
There is no Godot project in this repository. Collision, LOD and rig authoring are
not implied by GLB success.

## Явный цветовой атрибут вершин

Для данных, используемых шейдером независимо от узлов материала, задайте
`export <asset> --vertex-color-name OutlineWeight`. В Blender поле **Vertex Color
Attribute / Цветовой атрибут вершин** находится в панели вывода. Core API:
`export_asset(..., vertex_color_name="OutlineWeight")`; общий запрос операции
передаёт строку `vertex_color_name`. Опция относится только к GLB export и может
использоваться вместе с `--animations`.

Непустое имя обязано существовать в `mesh.color_attributes` каждого включённого
меша. До записи GLB выполняется проверка; ошибка называет отсутствующий атрибут
и меши. Helpers и чужие объекты не участвуют. Используется штатный glTF exporter
с `export_vertex_color="NAME"`, указанным именем и
`export_all_vertex_colors=False`: выбранный RGBA-слой становится `COLOR_0`,
включая alpha, даже если материал не читает его. Другие слои не добавляются.
Источник, активный цветовой слой и данные материала не редактируются.

Пустая строка по умолчанию не передаёт новых параметров Blender exporter и
сохраняет прежний выбор цветов по материалу. Никакой слой не добавляется,
не переименовывается и не заменяется белым. `--dry-run`, как и для остальных
параметров экспорта, показывает запрос без проверки будущего GLB.
Регрессия реального RGBA payload и оператора панели:

```powershell
python -m unittest discover -s tests -p "test_vertex_color_export.py"
blender --background --factory-startup --python-exit-code 1 --python tests/blender_vertex_color_export_test.py
```

## Экспорт скелета и клипов

CLI: `python -m game_asset_tools --project <project> export <asset> --animations`.
В Blender включите **Export Animations / Экспортировать анимации** в панели вывода.
Оба интерфейса вызывают `operations.execute({...,"action":"export","animations":True})`;
прямой Core API — `export_asset(..., animations=True)`. Остальные операции этот
флаг не принимают. Без флага сохраняется прежний экспорт без клипов.

Armature, меши и sockets должны быть зарегистрированы через `ctx.add` и
принадлежать одному ассету. Helpers не экспортируются. Каждому skinned mesh
нужен один включённый Armature modifier и ненулевые веса существующих костей.
Клипы — active Action либо Actions, сохранённые по одному в NLA track этого
объекта. Произвольные Actions из всего blend не назначаются ригу автоматически.
Составные NLA tracks и shape keys отклоняются с причиной; это экспорт жёстких
механизмов, а не обещание поддержки любых Blender deformation stacks.

Фаски и другие mesh modifiers применяет штатный glTF exporter к экспортной
геометрии. При `export_skins=True` он временно выключает Armature modifier,
сохраняя skeleton/weights. Исходные mesh data и модификаторы не применяются
разрушающим образом. Сохраняются текущий кадр/subframe, выбор, активный объект,
visibility и display units. Проверено в Blender 5.2.0 LTS.

Кандидат GLB сначала записывается во временный файл того же каталога. Проверка
реального payload сверяет кости/skin, родителей sockets, непустые клипы и
отсутствие чужих Actions. Только прошедший проверку файл заменяет delivery;
ошибка не уничтожает предыдущий GLB. Отчёт содержит `structure`,
`animation_contract`, `animations_requested` и warnings.

Проверяемый рецепт находится в `tests/fixtures/animated_rig`: два независимых
жёстких звена, Base/Hinge, swing/fold и TipSocket. Команды:

```powershell
python -m unittest discover -s tests -p "test_*.py"
blender --background --factory-startup --python-exit-code 1 --python tests/blender_animated_export_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/blender_animated_export_ui_test.py
blender --background --factory-startup --python-exit-code 1 --python tests/run_blender_tests.py
```

Результат на 2026-10-24: 60 Python, 6 animated-export, 3 UI (включая настоящий
экспорт оператором панели) и 13 workflow tests — PASS. Blender round-trip
проверяет движение socket/skin и сохранение фасок с жёсткими весами.
В primary Mech Battler 2 дополнительно выполнен GPU-import обоих GLB,
обычного и с фасками: по 19 проверок Godot 4.7.2. Внешний проверочный инструмент —
`tools/verify_gat_animated_import.gd -- --glb <absolute path>` того проекта;
его отчёт записывает корень игры и SHA256 GLB.

Это проверка экспорта, не готовая библиотека сменных деталей. Control rig,
совместимость sockets, безопасная замена модулей, ограничения суставов и
контакты/скольжение в анимациях остаются отдельными этапами. Установленные
копии аддона ещё не обновлены этим изменением.
