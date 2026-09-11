# Extending Core

Do not modify GameAssetTools Core merely to solve one asset-specific problem.
Search the relevant helper and one similar recipe. Combine existing helpers first;
keep unique raw bpy work in the recipe. Promote an operation only when it has a
clear second use and a useful semantic interface.

Core modules separate geometry, modifiers, transforms, materials, collections, and
naming. Keep context/state dependencies explicit. Preserve user selection, mode,
shared mesh users, and scene content. Add optional arguments for compatible growth;
document a migration for breaking recipe/config changes. Avoid new production
dependencies unless stdlib and Blender are insufficient.

Run pure tests for naming/config/registry changes and the relevant Blender suite
for geometry or lifecycle changes. Verify behavior (bounds, volume, ownership,
preservation, export), not merely syntax. A new helper should be exercised by a
representative recipe or a meaningful regression test. Update the smallest relevant
document and the changelog.
