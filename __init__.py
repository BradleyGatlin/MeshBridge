bl_info = {
    "name": "MeshBridge",
    "author": "MeshBridge contributors",
    "version": (0, 3, 1),
    "blender": (5, 3, 0),
    "location": "View3D > Sidebar > MeshBridge",
    "description": "Blender-native mesh import/export workbench.",
    "category": "Import-Export",
}

import bpy
from bpy.props import BoolProperty, FloatProperty, EnumProperty, PointerProperty
from bpy.types import PropertyGroup, Panel, Operator

from . import nostro, cmfet, rbxmodel


class MeshBridgeSettings(PropertyGroup):
    format: EnumProperty(
        name="Format",
        items=[
            ("NOSTRO", "Nostro", "Nostro mesh format"),
            ("CMFET", "CMFET", "Compact Mesh Format Extended Type"),
        ],
        default="NOSTRO",
    )
    import_scale: FloatProperty(
        name="Scale",
        description="Changes the size of imported geometry. Default: 1.00",
        default=1.0, min=0.0001, max=100000.0,
    )
    import_armature: BoolProperty(
        name="Detect Rig",
        description="Detect Roblox character rigs when rig support is available.",
        default=True,
    )
    include_normals: BoolProperty(
        name="Normals",
        description="Store vertex normals in CMFET exports.",
        default=False,
    )
    include_uvs: BoolProperty(
        name="UVs",
        description="Store UV coordinates in CMFET exports.",
        default=False,
    )
    select_imported: BoolProperty(
        name="Select Imported",
        description="Select newly imported objects.",
        default=True,
    )
    frame_imported: BoolProperty(
        name="Frame Imported",
        description="Frame imported objects in the 3D View.",
        default=True,
    )
    apply_scale: BoolProperty(
        name="Apply Scale",
        description="Apply import scale to the mesh after importing.",
        default=False,
    )
    rb_mesh_version: EnumProperty(
        name="Version",
        description="Roblox mesh version target/detection",
        items=[
            ("AUTO", "Auto", "Detect the mesh version"),
            ("1.00", "1.00", "Roblox mesh version 1.00"),
            ("1.01", "1.01", "Roblox mesh version 1.01"),
            ("2.00", "2.00", "Roblox mesh version 2.00"),
            ("3.00", "3.00", "Roblox mesh version 3.00"),
            ("3.01", "3.01", "Roblox mesh version 3.01"),
            ("4.00", "4.00", "Roblox mesh version 4.00"),
            ("4.01", "4.01", "Roblox mesh version 4.01"),
            ("5.00", "5.00", "Roblox mesh version 5.00"),
        ],
        default="AUTO",
    )


class MESHBRIDGE_OT_reset(Operator):
    bl_idname = "meshbridge.reset"
    bl_label = "Reset MeshBridge Settings"
    bl_options = {"UNDO"}

    def execute(self, context):
        s = context.scene.meshbridge
        s.format = "NOSTRO"
        s.import_scale = 1.0
        s.import_armature = True
        s.include_normals = False
        s.include_uvs = False
        s.select_imported = True
        s.frame_imported = True
        s.apply_scale = False
        s.rb_mesh_version = "AUTO"
        self.report({"INFO"}, "MeshBridge settings reset.")
        return {"FINISHED"}


class MESHBRIDGE_OT_frame(Operator):
    bl_idname = "meshbridge.frame"
    bl_label = "Frame Selected"
    bl_options = {"UNDO"}

    def execute(self, context):
        if not context.selected_objects:
            self.report({"WARNING"}, "Nothing is selected.")
            return {"CANCELLED"}
        if context.area and context.area.type == "VIEW_3D":
            bpy.ops.view3d.view_selected(use_all_regions=False)
            return {"FINISHED"}
        self.report({"INFO"}, "Frame Selected is available from a 3D View.")
        return {"CANCELLED"}


class MESHBRIDGE_PT_sidebar(Panel):
    bl_idname = "MESHBRIDGE_PT_sidebar"
    bl_label = "MeshBridge"
    bl_category = "MeshBridge"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        layout = self.layout
        s = context.scene.meshbridge
        obj = context.object

        # Simple header; avoid turning the entire sidebar into nested boxes.
        row = layout.row()
        row.label(text="MeshBridge", icon="MESH_DATA")

        # Primary actions.
        col = layout.column(align=True)
        col.label(text="Import", icon="IMPORT")

        row = col.row(align=True)
        row.operator("meshbridge.import_rbxm", text="Roblox Model", icon="IMPORT")
        row.operator("meshbridge.import_rbxplace", text="Roblox Place", icon="IMPORT")

        row = col.row(align=True)
        row.operator("meshbridge.import_nostro", text="Nostro", icon="IMPORT")
        row.operator("meshbridge.import_cmfet", text="CMFET", icon="IMPORT")

        layout.separator()

        col = layout.column(align=True)
        col.label(text="Export", icon="EXPORT")
        row = col.row(align=True)
        row.operator("meshbridge.export_nostro", text="Nostro", icon="EXPORT")
        row.operator("meshbridge.export_cmfet", text="CMFET", icon="EXPORT")

        layout.separator()

        # Roblox mesh settings, compact and unobtrusive.
        box = layout.box()
        box.label(text="Roblox Mesh", icon="OUTLINER_COLLECTION")
        row = box.row()
        row.prop(s, "rb_mesh_version", text="Version")
        row = box.row()
        row.prop(s, "import_scale", text="Scale")
        box.prop(s, "import_armature")

        layout.separator()

        box = layout.box()
        box.label(text="Options", icon="PREFERENCES")
        box.prop(s, "select_imported")
        box.prop(s, "frame_imported")
        box.prop(s, "apply_scale")

        if s.format == "CMFET":
            box.separator()
            box.label(text="CMFET", icon="MESH_DATA")
            box.prop(s, "include_normals")
            box.prop(s, "include_uvs")

        layout.separator()

        # Only the useful mesh information requested: UVs and materials.
        box = layout.box()
        box.label(text="Selected Mesh", icon="OBJECT_DATA")
        if obj and obj.type == "MESH":
            box.label(text=obj.name, icon="MESH_DATA")
            row = box.row()
            row.label(text="UV Maps")
            row.label(text=str(len(obj.data.uv_layers)))
            row = box.row()
            row.label(text="Materials")
            row.label(text=str(len(obj.data.materials)))
        else:
            box.label(text="No mesh selected.", icon="INFO")

        row = layout.row(align=True)
        row.operator("meshbridge.frame", text="Frame Selected", icon="VIEWZOOM")
        row.operator("meshbridge.reset", text="Reset", icon="LOOP_BACK")


def menu_import(self, context):
    self.layout.operator(
        "meshbridge.import_rbxm",
        text="Roblox Model (.rbxm)",
        icon="IMPORT",
    )
    self.layout.operator(
        "meshbridge.import_rbxplace",
        text="Roblox Place (.rbxl)",
        icon="IMPORT",
    )
    self.layout.separator()
    self.layout.operator(
        "meshbridge.import_nostro",
        text="Nostro Mesh (.mesh)",
        icon="IMPORT",
    )
    self.layout.operator(
        "meshbridge.import_cmfet",
        text="CMFET (.cmfet)",
        icon="IMPORT",
    )


def menu_export(self, context):
    self.layout.operator(
        "meshbridge.export_nostro",
        text="Nostro Mesh (.mesh)",
        icon="EXPORT",
    )
    self.layout.operator(
        "meshbridge.export_cmfet",
        text="CMFET (.cmfet)",
        icon="EXPORT",
    )



class MESHBRIDGE_OT_show_report(Operator):
    bl_idname = "meshbridge.show_report"
    bl_label = "Open Import Report"

    def execute(self, context):
        name = context.scene.get("MeshBridge_LastImportReport", "MeshBridge Import Report")
        text = bpy.data.texts.get(name)
        if text is None:
            self.report({"WARNING"}, "No import report exists yet.")
            return {"CANCELLED"}
        # Switch current area to Text Editor when possible.
        if context.area:
            context.area.type = "TEXT_EDITOR"
            context.area.spaces.active.text = text
        return {"FINISHED"}


class MESHBRIDGE_OT_inspect(Operator):
    bl_idname = "meshbridge.inspect"
    bl_label = "Inspect Roblox Data"

    def execute(self, context):
        obj=context.object
        if obj is None:
            self.report({"WARNING"}, "Select an imported object first.")
            return {"CANCELLED"}
        lines=["MESHBRIDGE ASSET INSPECTOR","==========================",
               f"Name: {obj.name}",
               f"Type: {obj.type}"]
        for k,v in obj.items():
            if str(k).startswith("Roblox_") or str(k).startswith("MeshBridge_"):
                lines.append(f"{k}: {v}")
        text=bpy.data.texts.get("MeshBridge Asset Inspector") or bpy.data.texts.new("MeshBridge Asset Inspector")
        text.clear(); text.write("\n".join(lines))
        if context.area:
            context.area.type="TEXT_EDITOR"
            context.area.spaces.active.text=text
        return {"FINISHED"}

classes = (
    MeshBridgeSettings,
    MESHBRIDGE_OT_show_report,
    MESHBRIDGE_OT_inspect,
    MESHBRIDGE_OT_reset,
    MESHBRIDGE_OT_frame,
    MESHBRIDGE_PT_sidebar,
)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.meshbridge = PointerProperty(type=MeshBridgeSettings)
    nostro.register()
    cmfet.register()
    rbxmodel.register()
    bpy.types.TOPBAR_MT_file_import.append(menu_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_export)

def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_export)
    rbxmodel.unregister()
    cmfet.unregister()
    nostro.unregister()
    del bpy.types.Scene.meshbridge
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
