# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import random
import bpy
bl_info = {
    "name": "VertexColor2Materials (Plasticity + QuadRemesher)",
    "author": "Nolca",
    "description": "搭配Plasticity + QuadRemesher使用",
    "blender": (2, 80, 0),
    "version": (0, 0, 2),
    "location": "View3D > Sidebar > Plasticity",
    "warning": "",
    "category": "Mesh"
}


class VC2M_PropertyGroup(bpy.types.PropertyGroup):
    threashold_Tooltip = "默认0.98，建议0.97~1.0\n若此值为0.5，某物体总共有100个面，则执行时，会忽略面积较小的50个面"
    vc2m_ignore_area_smaller_than: bpy.props.FloatProperty(name="Ignore Area Smaller Than",
                                        description=threashold_Tooltip,
                                        default=0.98, min=0, max=1, step=0.05,precision=3,subtype='FACTOR')


class PLASTICITY_PT_Panel_VC2M(bpy.types.Panel):
    """Creates a Panel in the Object properties window"""
    bl_label = "Materials"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Plasticity'

    def draw(self, context):
        layout = self.layout
        props = context.scene.v2cm
        row = layout.row()
        row.prop(props, 'vc2m_ignore_area_smaller_than', text='忽略小于')
        row = layout.row()
        row.operator("materials.convert_to_materials",icon='ORPHAN_DATA')
        row = layout.row()
        row.operator("materials.clear_obj_materials",icon='TRASH')
        row = layout.row()
        row.operator("wm.refacet_batch")

class RefacetBatchOperator(bpy.types.Operator):
    bl_idname = "wm.refacet_batch"
    bl_label = "批量refacet"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "选中物体批量重拓扑\nrefacet the selected objects batchly"

    def execute(self, context):
        selected_objects = bpy.context.selected_objects
        for obj in selected_objects:
            if obj.type != 'MESH':
                continue
            bpy.ops.object.select_all(action='DESELECT')
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.wm.refacet()
        return {'FINISHED'}


class ConvertMaterialsOperator(bpy.types.Operator):
    bl_idname = "materials.convert_to_materials"
    bl_label = "顶点颜色转材质"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description="此操作将自动清理未使用的数据块\n若按钮为灰，不可点击，则激活物体非plasticity对象\n\n与QuadRemesher搭配:\n0. 若nPoly，则先三角化\n1. 使用材质 ☑\n2. 使用法线分割 ☑\n3. 按角度检测硬边 可选勾\n4. 有对称性: ☑"

    @classmethod
    def poll(cls, context):
        return any("plasticity_id" in obj.keys() and obj.type == 'MESH' for obj in context.selected_objects)

    def execute(self, context):
        prev_obj_mode = bpy.context.mode

        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            if not "plasticity_id" in obj.keys():
                continue
            mesh = obj.data

            if "plasticity_id" not in obj.keys():
                self.report(
                    {'ERROR'}, "Object doesn't have a plasticity_id attribute.")
                return {'CANCELLED'}

            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='OBJECT')

            # delete all materials of the object
            obj.data.materials.clear()
            bpy.ops.outliner.orphans_purge(
                do_local_ids=True, do_linked_ids=True, do_recursive=False)
            self.colorize_mesh(obj, mesh)

        return {'FINISHED'}

    def colorize_mesh(self, obj, mesh):
        groups = mesh["groups"]
        face_ids = mesh["face_ids"]

        if len(groups) == 0:
            return
        if len(face_ids) * 2 != len(groups):
            return

        if not mesh.vertex_colors:
            mesh.vertex_colors.new()
        color_layer = mesh.vertex_colors.active

        group_idx = 0
        # groups: group_start,group_count ,group_start,group_count,...
        group_start = groups[group_idx * 2 + 0]
        group_count = groups[group_idx * 2 + 1]
        face_id = face_ids[group_idx]
        # print(face_id,*face_ids)
        color = generate_color_by_density(face_id)

        areas = [poly.area for poly in mesh.polygons]
        areas.sort()
        props = bpy.context.scene.v2cm
        threashold = areas[int((len(areas)-1)*getattr(props,'vc2m_ignore_area_smaller_than'))]
        # print(areas,threashold,int((len(areas)-1)*getattr(props,'vc2m_ignore_area_smaller_than')))

        for poly in mesh.polygons:
            # if the longest edge of the face is longer than the threshold, skip
            loop_start = poly.loop_start
            if loop_start >= group_start + group_count:
                group_idx += 1
                group_start = groups[group_idx * 2 + 0]
                group_count = groups[group_idx * 2 + 1]
                face_id = face_ids[group_idx]
                color = generate_color_by_density(face_id)

            if poly.area < threashold:
                mesh.polygons[poly.index].material_index = 0
                continue

            # Create a new material
            mat = bpy.data.materials.new(name="M."+str(face_id))
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes["Principled BSDF"]
            bsdf.inputs[0].default_value = color
            obj.data.materials.append(mat)

            mesh.polygons[poly.index].material_index = len(obj.data.materials)-1
            for loop_index in range(loop_start, loop_start + poly.loop_total):
                color_layer.data[loop_index].color = color

class ClearObjMaterialsOperator(bpy.types.Operator):
    bl_idname = "materials.clear_obj_materials"
    bl_label = "删除材质"
    bl_options = {'REGISTER', 'UNDO'}
    bl_description = "删除所选对象的所有材质\n执行后需自行清理文件块\n文件>清理>..."

    def execute(self, context):
        for obj in context.selected_objects:
            if obj.type != 'MESH':
                continue
            obj.data.materials.clear()
        return {'FINISHED'}

# todo: generate color by density
def generate_color_by_density(face_id):
    return (random.random(), random.random(), random.random(), 1.0)


classes = (
    PLASTICITY_PT_Panel_VC2M,
    ConvertMaterialsOperator,
    ClearObjMaterialsOperator,
    VC2M_PropertyGroup,
    RefacetBatchOperator,
)


def register():
    for i in classes:
        bpy.utils.register_class(i)
    bpy.types.Scene.v2cm = bpy.props.PointerProperty(type=VC2M_PropertyGroup)


def unregister():
    for i in classes:
        bpy.utils.unregister_class(i)


if __name__ == "__main__":
    register()
